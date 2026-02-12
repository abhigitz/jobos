"""Morning briefing task — sends daily plan at 8:30 AM IST via Claude."""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from app.config import get_settings
from app.models.daily_log import DailyLog
from app.models.job import Job
from app.models.content import ContentCalendar
from app.models.profile import ProfileDNA
from app.models.user import User
from app.services.telegram_service import send_telegram_message
from app.services.ai_service import generate_morning_briefing
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def morning_briefing_task() -> None:
    """
    Runs at 8:30 AM IST (3:00 AM UTC) Mon-Sat.
    Pulls pipeline, stale apps, content topic, yesterday's log, streak.
    Calls generate_morning_briefing() for Claude-generated plan.
    Sends result via Telegram.
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id
    owner_email = settings.owner_email

    if not chat_id or not owner_email:
        logger.warning("Morning briefing: owner not configured, skipping")
        return

    now_ist = datetime.now(IST)
    today_ist = now_ist.date()
    logger.info(f"Morning briefing running for {today_ist}")

    try:
        async with get_task_session() as db:
            # Find owner user
            result = await db.execute(
                select(User).where(User.email == owner_email)
            )
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"Morning briefing: user not found for {owner_email}")
                return

            # 1. Pipeline snapshot (exclude Closed)
            result = await db.execute(
                select(Job.status, func.count()).where(
                    Job.user_id == user.id,
                    Job.is_deleted.is_(False),
                    Job.status != 'Closed',
                ).group_by(Job.status)
            )
            pipeline = {status: count for status, count in result.all()}

            # 2. Stale applications (Applied 5+ days ago, no update since)
            stale_cutoff = today_ist - timedelta(days=5)
            result = await db.execute(
                select(Job.company_name, Job.role_title, Job.applied_date).where(
                    Job.user_id == user.id,
                    Job.status == 'Applied',
                    Job.is_deleted.is_(False),
                    Job.applied_date != None,
                    Job.applied_date <= stale_cutoff,
                ).order_by(Job.applied_date).limit(5)
            )
            stale_jobs = result.all()

            # 3. Today's content topic
            result = await db.execute(
                select(ContentCalendar.topic, ContentCalendar.category).where(
                    ContentCalendar.user_id == user.id,
                    ContentCalendar.scheduled_date == today_ist,
                    ContentCalendar.status == 'Planned',
                ).limit(1)
            )
            content_row = result.first()

            # 4. Yesterday's log (skip Sunday — if today is Monday, check Saturday)
            if now_ist.weekday() == 0:  # Monday
                last_workday = today_ist - timedelta(days=2)
            else:
                last_workday = today_ist - timedelta(days=1)

            result = await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date == last_workday,
                )
            )
            yesterday_log = result.scalar_one_or_none()

            # 5. Application streak (consecutive working days with apps > 0)
            result = await db.execute(
                select(DailyLog.log_date, DailyLog.jobs_applied).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date <= today_ist,
                ).order_by(DailyLog.log_date.desc()).limit(14)
            )
            recent_logs = result.all()
            log_dict = {row.log_date: row.jobs_applied for row in recent_logs}

            streak = 0
            for i in range(1, 15):
                d = today_ist - timedelta(days=i)
                if d.weekday() == 6:  # Skip Sunday
                    continue
                if d in log_dict and log_dict[d] > 0:
                    streak += 1
                else:
                    break

        # Build data dict for generate_morning_briefing()
        # generate_morning_briefing() does json.dumps(data) into the prompt,
        # so all keys are available to the Claude model.
        pipeline_str = ", ".join(
            f"{s}: {c}" for s, c in pipeline.items()
        ) if pipeline else "Empty pipeline"

        stale_str = "; ".join(
            f"{j.company_name} / {j.role_title} (applied {j.applied_date})"
            for j in stale_jobs
        ) if stale_jobs else "All caught up"

        yesterday_str = (
            f"{yesterday_log.jobs_applied} apps, "
            f"{yesterday_log.connections_sent} connections, "
            f"{yesterday_log.comments_made} comments"
        ) if yesterday_log else "No log recorded"

        content_topic = (
            f"{content_row.topic} ({content_row.category})"
        ) if content_row else None

        data = {
            "date": today_ist.strftime("%A, %B %d, %Y"),
            "date_short": today_ist.strftime("%A, %b %d"),
            "pipeline": pipeline_str,
            "pipeline_counts": pipeline,
            "stale_applications": stale_str,
            "stale_jobs": [
                {"company": j.company_name, "role": j.role_title, "applied_date": str(j.applied_date)}
                for j in stale_jobs
            ],
            "yesterday_summary": yesterday_str,
            "yesterday_log": {
                "jobs_applied": yesterday_log.jobs_applied if yesterday_log else 0,
                "connections_sent": yesterday_log.connections_sent if yesterday_log else 0,
                "comments_made": yesterday_log.comments_made if yesterday_log else 0,
            } if yesterday_log else None,
            "streak": streak,
            "content_topic": content_topic,
        }

        # Call the existing AI wrapper (has retries built in)
        briefing_text = await generate_morning_briefing(data)

        if not briefing_text:
            # Claude failed — send static fallback
            briefing_text = (
                f"MORNING BRIEFING — {today_ist.strftime('%A, %b %d')}\n\n"
                f"PIPELINE: {pipeline_str}\n\n"
                f"TODAY'S PRIORITIES:\n"
                f"1. Apply to 3-5 roles\n"
                f"2. Follow up on stale applications\n"
                f"3. Send 3 connection requests\n\n"
                f"FOLLOW-UP NEEDED:\n{stale_str}\n\n"
                f"STREAK: {streak} days"
            )

        msg = f"☀️ {briefing_text}"
        await send_telegram_message(chat_id, msg)
        logger.info(f"Morning briefing sent to chat_id={chat_id}")

    except Exception as e:
        logger.error(f"Morning briefing failed: {e}", exc_info=True)
        try:
            await send_telegram_message(
                chat_id,
                "☀️ MORNING BRIEFING\n\n"
                "System error generating briefing.\n\n"
                "Start your day:\n"
                "1. Apply to 3 roles\n"
                "2. Send 3 connections\n"
                "3. Comment on 2 posts\n\n"
                "/pipeline to check status"
            )
        except Exception:
            pass
