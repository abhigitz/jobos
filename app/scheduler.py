"""APScheduler setup for JobOS background tasks."""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def register_jobs() -> None:
    """Register all scheduled jobs. Called once at startup."""
    from app.tasks.evening_checkin import evening_checkin_task
    from app.tasks.midday_check import midday_check_task
    from app.tasks.morning_briefing import morning_briefing_task
    from app.tasks.linkedin_content import linkedin_content_task
    from app.tasks.weekly_review import weekly_review_task

    # All times in UTC. Railway runs UTC.

    # 8:30 AM IST = 3:00 AM UTC — Mon-Sat
    scheduler.add_job(
        morning_briefing_task,
        CronTrigger(hour=3, minute=0, day_of_week="mon-sat"),
        id="morning_briefing",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 2:00 PM IST = 8:30 AM UTC — Mon-Sat
    scheduler.add_job(
        midday_check_task,
        CronTrigger(hour=8, minute=30, day_of_week="mon-sat"),
        id="midday_check",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 6:30 PM IST = 1:00 PM UTC — Mon-Sat
    scheduler.add_job(
        evening_checkin_task,
        CronTrigger(hour=13, minute=0, day_of_week="mon-sat"),
        id="evening_checkin",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 7:00 PM IST = 1:30 PM UTC — Mon-Sat
    scheduler.add_job(
        linkedin_content_task,
        CronTrigger(hour=13, minute=30, day_of_week="mon-sat"),
        id="linkedin_content",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Sunday 9:00 AM IST = 3:30 AM UTC
    scheduler.add_job(
        weekly_review_task,
        CronTrigger(hour=3, minute=30, day_of_week="sun"),
        id="weekly_review",
        replace_existing=True,
        misfire_grace_time=300,
    )

    logger.info(
        "Scheduler jobs registered: "
        "morning (03:00 UTC), midday (08:30 UTC), "
        "evening (13:00 UTC), linkedin (13:30 UTC), "
        "weekly (Sun 03:30 UTC)"
    )


def start_scheduler() -> None:
    register_jobs()
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
