"""Weekly review task — sends performance summary on Sunday 9:00 AM IST."""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from app.config import get_settings
from app.models.daily_log import DailyLog
from app.models.job import Job
from app.models.content import ContentCalendar
from app.models.weekly_metrics import WeeklyMetrics
from app.models.user import User
from app.services.telegram_service import send_telegram_message
from app.services.ai_service import generate_weekly_review
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def weekly_review_task() -> None:
    """
    Runs at 9:00 AM IST (3:30 AM UTC) on Sundays.
    Aggregates past week's activity from daily_logs and jobs.
    Calls generate_weekly_review() for Claude analysis.
    Saves to weekly_metrics, sends via Telegram.
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id
    owner_email = settings.owner_email

    if not chat_id or not owner_email:
        logger.warning("Weekly review: owner not configured, skipping")
        return

    today_ist = datetime.now(IST).date()
    # Week = Monday through Saturday (6 working days)
    week_end = today_ist - timedelta(days=1)      # Saturday
    week_start = today_ist - timedelta(days=6)     # Monday
    logger.info(f"Weekly review running for {week_start} to {week_end}")

    try:
        async with get_task_session() as db:
            # Find owner user
            result = await db.execute(
                select(User).where(User.email == owner_email)
            )
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"Weekly review: user not found for {owner_email}")
                return

            # 1. Daily logs for the week
            result = await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date >= week_start,
                    DailyLog.log_date <= week_end,
                ).order_by(DailyLog.log_date)
            )
            logs = result.scalars().all()

            # Aggregate
            days_logged = len(logs)
            total_apps = sum(l.jobs_applied for l in logs)
            total_connections = sum(l.connections_sent for l in logs)
            total_comments = sum(l.comments_made for l in logs)
            total_calls = sum(l.networking_calls for l in logs)
            total_referrals = sum(l.referrals_asked for l in logs)
            naukri_days = sum(1 for l in logs if l.naukri_updated)
            post_days = sum(1 for l in logs if l.post_published)

            # 2. Pipeline snapshot (all statuses)
            result = await db.execute(
                select(Job.status, func.count()).where(
                    Job.user_id == user.id,
                    Job.is_deleted.is_(False),
                ).group_by(Job.status)
            )
            pipeline = {status: count for status, count in result.all()}

            # 3. New jobs added this week
            # Use UTC timestamps for created_at comparison (stored as UTC in DB)
            week_start_utc = datetime.combine(
                week_start, datetime.min.time()
            ).replace(tzinfo=timezone.utc)

            result = await db.execute(
                select(Job.company_name, Job.role_title, Job.fit_score, Job.ats_score).where(
                    Job.user_id == user.id,
                    Job.is_deleted.is_(False),
                    Job.created_at >= week_start_utc,
                ).order_by(Job.fit_score.desc().nulls_last()).limit(10)
            )
            new_jobs = result.all()

            # 4. Content published this week
            result = await db.execute(
                select(func.count()).select_from(ContentCalendar).where(
                    ContentCalendar.user_id == user.id,
                    ContentCalendar.status.in_(['Published', 'Drafted', 'Reviewed']),
                    ContentCalendar.scheduled_date >= week_start,
                    ContentCalendar.scheduled_date <= week_end,
                )
            )
            content_count = result.scalar() or 0

        # Build daily breakdown string
        daily_lines = []
        for log in logs:
            daily_lines.append(
                f"{log.log_date.strftime('%a')}: "
                f"{log.jobs_applied} apps, "
                f"{log.connections_sent} conn, "
                f"{log.comments_made} comments"
            )
        daily_breakdown = "\n".join(daily_lines) if daily_lines else "No daily logs this week"

        new_jobs_lines = []
        for job in new_jobs:
            parts = [f"{job.company_name} / {job.role_title}"]
            if job.fit_score:
                parts.append(f"fit:{job.fit_score}")
            if job.ats_score:
                parts.append(f"ATS:{job.ats_score}")
            new_jobs_lines.append(" ".join(parts))
        new_jobs_str = "\n".join(new_jobs_lines) if new_jobs_lines else "None"

        pipeline_str = ", ".join(f"{s}: {c}" for s, c in pipeline.items()) if pipeline else "Empty"

        # Build data dict for generate_weekly_review()
        # generate_weekly_review() does json.dumps(data) into the prompt,
        # so all keys are available to the Claude model.
        data = {
            "week_start": week_start.strftime("%b %d"),
            "week_end": week_end.strftime("%b %d"),
            "daily_breakdown": daily_breakdown,
            "days_logged": days_logged,
            "total_apps": total_apps,
            "total_applications": total_apps,
            "total_connections": total_connections,
            "total_comments": total_comments,
            "total_calls": total_calls,
            "total_referrals": total_referrals,
            "naukri_days": naukri_days,
            "post_days": post_days,
            "posts_published": post_days,
            "pipeline": pipeline_str,
            "pipeline_counts": pipeline,
            "new_jobs": new_jobs_str,
            "new_jobs_list": [
                {"company": j.company_name, "role": j.role_title, "fit_score": j.fit_score}
                for j in new_jobs
            ],
            "content_published": content_count,
        }

        # Call existing AI wrapper (has retries)
        review_text = await generate_weekly_review(data)

        if not review_text:
            # Fallback: send raw data
            review_text = (
                f"WEEKLY REVIEW — Week of {week_start.strftime('%b %d')}\n\n"
                f"SCORECARD:\n"
                f"Applications: {total_apps}\n"
                f"Connections: {total_connections}\n"
                f"Comments: {total_comments}\n"
                f"Posts: {post_days}/6\n"
                f"Logging: {days_logged}/6 days\n\n"
                f"PIPELINE: {pipeline_str}\n\n"
                f"(AI analysis unavailable)"
            )

        # Save to weekly_metrics
        try:
            async with get_task_session() as db:
                result = await db.execute(
                    select(User).where(User.email == owner_email)
                )
                user = result.scalar_one_or_none()

                if user:
                    week_num = today_ist.isocalendar()[1]
                    metrics = WeeklyMetrics(
                        user_id=user.id,
                        week_number=week_num,
                        week_start=week_start,
                        week_end=week_end,
                        total_applied=total_apps,
                        total_connections=total_connections,
                        total_calls=total_calls,
                        total_referrals=total_referrals,
                        posts_published=post_days,
                        whats_working="See ai_analysis",
                        whats_not="See ai_analysis",
                        key_adjustment="See ai_analysis",
                        ai_analysis=review_text,
                    )
                    db.add(metrics)
                    await db.commit()
                    logger.info(f"Weekly metrics saved for week {week_num}")
        except Exception as e:
            logger.error(f"Failed to save weekly metrics: {e}")

        msg = f"📈 {review_text}"
        await send_telegram_message(chat_id, msg)
        logger.info(f"Weekly review sent to chat_id={chat_id}")

    except Exception as e:
        logger.error(f"Weekly review failed: {e}", exc_info=True)
        try:
            await send_telegram_message(
                chat_id,
                "📈 WEEKLY REVIEW\n\n"
                "System error generating review.\n\n"
                "/pipeline to check status\n"
                "/log to record today"
            )
        except Exception:
            pass
