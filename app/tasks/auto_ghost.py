"""Auto-ghost task - closes stale Applied jobs after 14 days."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.models.job import Job
from app.models.user import User
from app.services.telegram_service import send_telegram_message
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def auto_ghost_task() -> None:
    """
    Runs at 2:55 AM UTC (8:25 AM IST) Mon-Sat.

    1. Auto-ghosts: jobs in Applied for 14+ days with no updates
    2. Warns: jobs in Applied for 12-14 days (will be ghosted soon)
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id
    owner_email = settings.owner_email

    if not chat_id or not owner_email:
        logger.warning("Auto-ghost: owner not configured, skipping")
        return

    now_utc = datetime.now(timezone.utc)
    ghost_cutoff = now_utc - timedelta(days=14)
    warn_cutoff = now_utc - timedelta(days=12)

    try:
        async with get_task_session() as db:
            # Find owner user
            result = await db.execute(select(User).where(User.email == owner_email))
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"Auto-ghost: user not found for {owner_email}")
                return

            # 1. Find jobs to auto-ghost (14+ days stale)
            result = await db.execute(
                select(Job).where(
                    Job.user_id == user.id,
                    Job.status == "Applied",
                    Job.is_deleted.is_(False),
                    Job.updated_at < ghost_cutoff,
                )
            )
            ghost_jobs = result.scalars().all()

            ghosted_names = []
            for job in ghost_jobs:
                days_stale = (now_utc - job.updated_at).days
                job.status = "Closed"
                job.closed_reason = "Ghosted"
                existing_notes = job.notes if job.notes is not None else []
                existing_notes.append({
                    "text": f"Auto-closed: no response after {days_stale} days",
                    "created_at": now_utc.isoformat(),
                    "type": "system",
                })
                job.notes = existing_notes
                flag_modified(job, "notes")
                ghosted_names.append(f"{job.company_name} / {job.role_title} ({days_stale}d)")

            if ghost_jobs:
                await db.commit()
                logger.info(f"Auto-ghost: closed {len(ghost_jobs)} stale jobs")

            # 2. Find jobs approaching ghost (12-14 days, will be ghosted soon)
            result = await db.execute(
                select(Job).where(
                    Job.user_id == user.id,
                    Job.status == "Applied",
                    Job.is_deleted.is_(False),
                    Job.updated_at < warn_cutoff,
                    Job.updated_at >= ghost_cutoff,
                )
            )
            warn_jobs = result.scalars().all()
            warn_names = [f"{j.company_name} / {j.role_title}" for j in warn_jobs]

        # Send Telegram notifications
        if ghosted_names:
            msg = f"AUTO-GHOSTED ({len(ghosted_names)}):\n"
            msg += "\n".join(f"  {n}" for n in ghosted_names[:15])
            if len(ghosted_names) > 15:
                msg += f"\n  ...and {len(ghosted_names) - 15} more"
            msg += "\n\nReopen: update status in dashboard or /status CompanyName | Applied"
            await send_telegram_message(chat_id, msg)

        if warn_names:
            msg = f"GHOSTING IN 2 DAYS ({len(warn_names)}):\n"
            msg += "\n".join(f"  {n}" for n in warn_names[:15])
            msg += "\n\nUpdate these jobs to keep them active."
            await send_telegram_message(chat_id, msg)

        if not ghosted_names and not warn_names:
            logger.info("Auto-ghost: no stale or at-risk jobs found")

    except Exception as e:
        logger.error(f"Auto-ghost failed: {e}", exc_info=True)
