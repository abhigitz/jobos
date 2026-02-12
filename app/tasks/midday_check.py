"""Midday check task — sends nudge at 2:00 PM IST."""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.models.daily_log import DailyLog
from app.models.user import User
from app.services.telegram_service import send_telegram_message
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def midday_check_task() -> None:
    """
    Runs at 2:00 PM IST (8:30 AM UTC) Mon-Sat.
    Checks today's activity and last working day.
    No Claude API needed — pure template.
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id
    owner_email = settings.owner_email

    if not chat_id or not owner_email:
        logger.warning("Midday check: owner not configured, skipping")
        return

    now_ist = datetime.now(IST)
    today_ist = now_ist.date()
    is_saturday = now_ist.weekday() == 5  # Monday=0, Saturday=5
    logger.info(f"Midday check running for {today_ist}")

    try:
        async with get_task_session() as db:
            # Find owner user
            result = await db.execute(
                select(User).where(User.email == owner_email)
            )
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"Midday check: user not found for {owner_email}")
                return

            # Get today's log
            result = await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date == today_ist,
                )
            )
            today_log = result.scalar_one_or_none()

            # Get LAST WORKING DAY's log (not calendar yesterday)
            # Monday -> check Saturday (2 days back)
            # Tue-Sat -> check yesterday (1 day back)
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
            prev_log = result.scalar_one_or_none()

        # Build message — PLAIN TEXT ONLY (no Markdown bold/italic)
        day_str = today_ist.strftime("%A, %b %d")

        if today_log is None:
            # No log today — check if last working day was also empty
            prev_apps = prev_log.jobs_applied if prev_log else 0
            prev_missing = prev_log is None

            if prev_apps == 0 or prev_missing:
                msg = (
                    f"⚠️ MID-DAY CHECK — {day_str}\n\n"
                    f"No applications logged recently.\n"
                    f"The best time to apply is now.\n\n"
                    f"Quick wins for next 2 hours:\n"
                    f"  - Apply to 2 roles\n"
                    f"  - Send 2 connections\n"
                    f"  - Comment on 1 post\n\n"
                    f"/log to track progress"
                )
            else:
                msg = (
                    f"⏰ MID-DAY CHECK — {day_str}\n\n"
                    f"No activity logged yet today.\n\n"
                    f"Quick wins for next 2 hours:\n"
                    f"  - Apply to 2 roles\n"
                    f"  - Send 2 connections\n"
                    f"  - Comment on 1 post\n\n"
                    f"/log to track progress"
                )

        elif today_log.jobs_applied == 0:
            msg = (
                f"⏰ MID-DAY CHECK — {day_str}\n\n"
                f"{today_log.connections_sent} connections, "
                f"{today_log.comments_made} comments — "
                f"but 0 applications so far.\n\n"
                f"Afternoon focus: apply to 2-3 roles before 5 PM."
            )

        else:
            msg = (
                f"⏰ MID-DAY CHECK — {day_str}\n\n"
                f"{today_log.jobs_applied} apps, "
                f"{today_log.connections_sent} connections, "
                f"{today_log.comments_made} comments\n\n"
                f"Good momentum. Keep pushing this afternoon!"
            )

        if is_saturday:
            msg += "\n\n🗓️ Weekend push — even 1 application keeps the streak alive."

        await send_telegram_message(chat_id, msg)
        logger.info(f"Midday check sent to chat_id={chat_id}")

    except Exception as e:
        logger.error(f"Midday check failed: {e}", exc_info=True)
        # Fallback — still send something
        try:
            await send_telegram_message(
                chat_id,
                "⏰ MID-DAY CHECK\n\n"
                "System error generating check.\n\n"
                "How's the afternoon going?\n"
                "/log to track progress"
            )
        except Exception:
            pass
