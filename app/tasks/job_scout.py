"""Scheduled task for Job Scout -- automated job discovery."""
import logging

from app.config import get_settings
from app.services.scout_service import run_scout

logger = logging.getLogger(__name__)


async def job_scout_task() -> None:
    """Runs daily at 8:00 AM IST. Discovers and scores new jobs."""
    settings = get_settings()

    if not settings.owner_email:
        logger.warning("Job Scout: owner_email not configured, skipping")
        return

    if not settings.serper_api_key and not (settings.adzuna_app_id and settings.adzuna_api_key):
        logger.warning("Job Scout: no API keys configured (serper or adzuna), skipping")
        return

    try:
        summary = await run_scout()
        logger.info(
            f"Job Scout complete: fetched={summary.get('total_fetched', 0)}, "
            f"promoted={summary.get('promoted_to_pipeline', 0)}, "
            f"review={summary.get('saved_for_review', 0)}"
        )
    except Exception as e:
        logger.error(f"Job Scout task failed: {e}", exc_info=True)
        # Try to notify via Telegram
        try:
            from app.services.telegram_service import send_telegram_message
            chat_id = settings.owner_telegram_chat_id
            if chat_id:
                await send_telegram_message(
                    chat_id,
                    f"Job Scout error: {str(e)[:200]}",
                )
        except Exception:
            pass
