"""APScheduler setup for JobOS background tasks."""
import logging

from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

jobstores = {}
if settings.redis_url:
    jobstores["default"] = RedisJobStore(url=settings.redis_url)

scheduler = AsyncIOScheduler(jobstores=jobstores)


def register_jobs() -> None:
    """Register all scheduled jobs. Called once at startup."""
    from app.tasks.db_backup import run_daily_backup
    from app.tasks.evening_checkin import evening_checkin_task
    from app.tasks.midday_check import midday_check_task
    from app.tasks.morning_briefing import morning_briefing_task
    from app.tasks.linkedin_content import linkedin_content_task
    from app.tasks.weekly_review import weekly_review_task
    from app.tasks.auto_ghost import auto_ghost_task
    from app.tasks.job_scout import job_scout_task

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

    # 8:25 AM IST = 2:55 AM UTC, Mon-Sat (runs before morning briefing)
    scheduler.add_job(
        auto_ghost_task,
        CronTrigger(hour=2, minute=55, day_of_week="mon-sat"),
        id="auto_ghost",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 8:00 AM IST = 2:30 AM UTC, daily (Job Scout)
    scheduler.add_job(
        job_scout_task,
        CronTrigger(hour=2, minute=30),
        id="job_scout",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 2:00 AM UTC = 7:30 AM IST, daily (Database Backup)
    scheduler.add_job(
        run_daily_backup,
        CronTrigger(hour=2, minute=0),
        id="daily_backup",
        replace_existing=True,
        misfire_grace_time=3600,  # Run if missed within 1 hour
    )

    logger.info(
        "Scheduler jobs registered: "
        "job_scout (02:30 UTC), daily_backup (02:00 UTC), auto_ghost (02:55 UTC), "
        "morning (03:00 UTC), midday (08:30 UTC), evening (13:00 UTC), linkedin (13:30 UTC), "
        "weekly (Sun 03:30 UTC)"
    )


def start_scheduler() -> None:
    register_jobs()
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=True)  # Wait for running jobs to finish
    logger.info("Scheduler stopped")
