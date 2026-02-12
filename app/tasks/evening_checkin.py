"""Evening check-in task — sends daily prompt at 6:30 PM IST."""
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


async def evening_checkin_task() -> None:
    """
    Runs at 6:30 PM IST (1:00 PM UTC) Mon-Sat.
    Checks if daily log exists, sends appropriate nudge.
    No Claude API needed — pure template.
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id
    owner_email = settings.owner_email

    if not chat_id or not owner_email:
        logger.warning("Evening check-in: owner not configured, skipping")
        return

    today_ist = datetime.now(IST).date()
    logger.info(f"Evening check-in running for {today_ist}")

    try:
        async with get_task_session() as db:
            # Find owner user
            result = await db.execute(
                select(User).where(User.email == owner_email)
            )
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"Evening check-in: user not found for {owner_email}")
                return

            # Get today's daily log
            result = await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date == today_ist,
                )
            )
            log = result.scalar_one_or_none()

        # Build message — PLAIN TEXT ONLY (no Markdown bold/italic)
        # Reason: dynamic data with special chars (*, _, [) breaks Telegram Markdown parser
        day_str = today_ist.strftime("%A, %b %d")

        if log and log.jobs_applied > 0:
            msg = (
                f"📊 EVENING CHECK-IN — {day_str}\n\n"
                f"Today so far:\n"
                f"  Apps: {log.jobs_applied}\n"
                f"  Connections: {log.connections_sent}\n"
                f"  Comments: {log.comments_made}\n"
                f"  Post: {'yes' if log.post_published else 'no'}\n"
                f"  Calls: {log.networking_calls}\n"
                f"  Referrals: {log.referrals_asked}\n"
                f"  Naukri: {'yes' if log.naukri_updated else 'no'}\n\n"
                f"Want to update? Use /log\n\n"
                f"🔥 {log.jobs_applied} applications — nice work."
            )
        elif log and log.jobs_applied == 0:
            msg = (
                f"📊 EVENING CHECK-IN — {day_str}\n\n"
                f"Today so far:\n"
                f"  Connections: {log.connections_sent}\n"
                f"  Comments: {log.comments_made}\n"
                f"  But 0 applications.\n\n"
                f"Still time to squeeze one in before end of day.\n\n"
                f"/log to update your numbers"
            )
        else:
            msg = (
                f"📊 EVENING CHECK-IN — {day_str}\n\n"
                f"No activity logged today. How was your day?\n\n"
                f"/log jobs,connections,comments,post(y/n),calls,referrals,naukri(y/n),company\n\n"
                f"Example: /log 3,4,3,y,1,2,y,Swiggy\n"
                f"Zero day: /log 0,0,0,n,0,0,n,none"
            )

        await send_telegram_message(chat_id, msg)
        logger.info(f"Evening check-in sent to chat_id={chat_id}")

    except Exception as e:
        logger.error(f"Evening check-in failed: {e}", exc_info=True)
        # Fallback — still send something so the user gets nudged
        try:
            await send_telegram_message(
                chat_id,
                "📊 EVENING CHECK-IN\n\n"
                "System error generating summary.\n\n"
                "How was today?\n"
                "/log jobs,connections,comments,post(y/n),calls,referrals,naukri(y/n),company"
            )
        except Exception:
            pass
