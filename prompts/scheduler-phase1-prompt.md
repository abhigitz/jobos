# JobOS Scheduler — Phase 1 (Claude Code Prompt)

You are working on **JobOS**, a FastAPI + SQLAlchemy async + PostgreSQL backend deployed on **Railway** (server runs in UTC). The codebase uses `datetime.now(timezone.utc)` everywhere — never `datetime.utcnow()`.

---

## Codebase Examination Results

These are the verified patterns from the existing codebase. **Match them exactly.**

### 1. Dependencies (`requirements.txt`)
- `httpx==0.28.1` ✅ already installed
- `SQLAlchemy==2.0.46`
- `APScheduler` is **NOT installed** — you must add it

### 2. Startup Pattern (`app/main.py`)
Uses the **lifespan context manager** (NOT `@app.on_event`):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup code
    yield
    # shutdown code (currently empty)
```

### 3. Database Session (`app/database.py`)
```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from .config import get_settings

settings = get_settings()
DATABASE_URL = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```
**Key**: The session factory is `AsyncSessionLocal`. Scheduler tasks cannot use FastAPI's `Depends(get_db)` — they must create sessions directly via `async with AsyncSessionLocal() as session`.

### 4. Config (`app/config.py`)
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    app_url: str = ""
    # ... other fields ...

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```
**Note**: `extra = "ignore"` means unknown env vars are silently ignored. New settings fields need defaults.

### 5. DailyLog Model (`app/models/daily_log.py`)
```python
class DailyLog(Base, IDMixin, TimestampMixin):
    __tablename__ = "daily_log"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    log_date: Mapped[date] = mapped_column(Date(), nullable=False)
    jobs_applied: Mapped[int] = mapped_column(Integer, default=0)
    connections_sent: Mapped[int] = mapped_column(Integer, default=0)
    comments_made: Mapped[int] = mapped_column(Integer, default=0)
    post_published: Mapped[bool] = mapped_column(Boolean, default=False)
    networking_calls: Mapped[int] = mapped_column(Integer, default=0)
    referrals_asked: Mapped[int] = mapped_column(Integer, default=0)
    naukri_updated: Mapped[bool] = mapped_column(Boolean, default=False)
    # ... more optional fields ...
```
**Critical**: The date field is `log_date` (NOT `date` or `created_at`). UniqueConstraint on `(user_id, log_date)`.

### 6. Job Model (`app/models/job.py`)
- Status values: `'Tracking', 'Applied', 'Interview', 'Offer', 'Closed'`
- `applied_date: Mapped[date | None] = mapped_column(Date())`
- `is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)`
- `notes: Mapped[list | None] = mapped_column(JSONB, server_default='[]', default=list)`

### 7. Telegram Routing (`app/routers/telegram.py`)
Uses **if/elif chain** for command dispatch (NOT dict dispatch):
```python
if command == "/help":
    ...
if command == "/connect":
    ...
# ... more commands ...
await send_telegram_message(chat_id, "Unknown command. Use /help.")  # default (line 210)
return {"ok": True}  # line 211
```
The default "Unknown command" handler is at line 210. New test commands MUST be added BEFORE this line.

### 8. Telegram Send Function (`app/services/telegram_service.py`)
```python
async def send_telegram_message(chat_id: int, text: str) -> bool:
```
**Already exists. DO NOT duplicate.** Import from `app.services.telegram_service`.

### 9. Logging Pattern
```python
import logging
logger = logging.getLogger(__name__)
```

### 10. Owner Data (from `seed.py`)
- Email: `abhinav.jain.iitd@gmail.com`
- telegram_chat_id: `7019499883`
- User ID: Generated UUID (must query DB at runtime)

---

## Task A — ADD DEPENDENCY

Add `APScheduler>=3.10,<4.0` to `requirements.txt`. Insert it alphabetically (after `anyio`, before `async-timeout`). Use the package manager:

```bash
pip install "APScheduler>=3.10,<4.0"
```

Then update `requirements.txt` with the pinned version. **CRITICAL: APScheduler 4.x has a completely incompatible API. Pin to `<4.0`.**

---

## Task B — CONFIG CHANGES (`app/config.py`)

Add two new fields to the `Settings` class (after `frontend_url`):

```python
owner_telegram_chat_id: int = 0
owner_email: str = ""
```

Both have defaults so the app won't crash if env vars aren't set. On Railway, set:
- `OWNER_TELEGRAM_CHAT_ID=7019499883`
- `OWNER_EMAIL=abhinav.jain.iitd@gmail.com`

---

## Task C — SCHEDULER SCAFFOLD

Create file: `app/scheduler.py`

```python
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

    # 6:30 PM IST = 1:00 PM UTC — Mon-Sat
    scheduler.add_job(
        evening_checkin_task,
        CronTrigger(hour=13, minute=0, day_of_week="mon-sat"),
        id="evening_checkin",
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

    logger.info("Scheduler jobs registered: evening_checkin (13:00 UTC), midday_check (08:30 UTC)")


def start_scheduler() -> None:
    """Start the scheduler."""
    register_jobs()
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
```

**Key decisions:**
- `misfire_grace_time=300` — if the task fires up to 5 min late (e.g. after a Railway deploy), it still runs instead of being skipped.
- `replace_existing=True` — safe for restarts.
- Lazy imports inside `register_jobs()` to avoid circular imports.

---

## Task D — TASK DB SESSION HELPER

Create file: `app/tasks/__init__.py` (empty file)

Create file: `app/tasks/db.py`

```python
"""Database session factory for scheduler tasks.

Scheduler tasks run outside FastAPI's request lifecycle,
so they cannot use Depends(get_db). This provides a
standalone async context manager for DB sessions.
"""
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal


@asynccontextmanager
async def get_task_session() -> AsyncSession:
    """Yield an async DB session for use in scheduler tasks."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

**Why not reuse `get_db()`?** — `get_db()` is an async generator designed for FastAPI's dependency injection. It uses `yield` and relies on FastAPI to handle the lifecycle. Scheduler tasks need a proper context manager with explicit error handling.

---

## Task E — EVENING CHECK-IN TASK (6:30 PM IST)

Create file: `app/tasks/evening_checkin.py`

```python
"""Evening check-in task — sends daily summary at 6:30 PM IST."""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from app.config import get_settings
from app.models.daily_log import DailyLog
from app.models.job import Job
from app.models.user import User
from app.services.telegram_service import send_telegram_message
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def evening_checkin_task() -> None:
    """
    Runs at 6:30 PM IST (1:00 PM UTC) Mon-Sat.
    Sends the owner a daily summary via Telegram.
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id
    owner_email = settings.owner_email

    if not chat_id or not owner_email:
        logger.warning("Scheduler: owner_telegram_chat_id or owner_email not configured, skipping evening check-in")
        return

    today_ist = datetime.now(IST).date()
    logger.info(f"Evening check-in running for {today_ist}")

    try:
        async with get_task_session() as db:
            # Find owner user
            result = await db.execute(select(User).where(User.email == owner_email))
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"Scheduler: owner user not found for email {owner_email}")
                return

            # Get today's daily log
            result = await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date == today_ist,
                )
            )
            log = result.scalar_one_or_none()

            # Get today's job applications
            result = await db.execute(
                select(func.count()).select_from(Job).where(
                    Job.user_id == user.id,
                    Job.applied_date == today_ist,
                    Job.is_deleted.is_(False),
                )
            )
            jobs_applied_today = result.scalar() or 0

            # Get active pipeline counts
            result = await db.execute(
                select(Job.status, func.count()).where(
                    Job.user_id == user.id,
                    Job.is_deleted.is_(False),
                    Job.status.in_(["Applied", "Interview", "Offer"]),
                ).group_by(Job.status)
            )
            pipeline = {status: count for status, count in result.all()}

            # Build message
            msg = f"🌆 *Evening Check-in — {today_ist.strftime('%A, %b %d')}*\n\n"

            if log:
                msg += "📊 *Today's Activity:*\n"
                msg += f"• Jobs applied: {log.jobs_applied}\n"
                msg += f"• Connections sent: {log.connections_sent}\n"
                msg += f"• Comments made: {log.comments_made}\n"
                msg += f"• Post published: {'✅' if log.post_published else '❌'}\n"
                msg += f"• Networking calls: {log.networking_calls}\n"
                msg += f"• Referrals asked: {log.referrals_asked}\n"
                msg += f"• Naukri updated: {'✅' if log.naukri_updated else '❌'}\n"
            else:
                msg += "⚠️ *No daily log recorded today.*\n"
                msg += "Use /log to record your activity before the day ends.\n"

            msg += f"\n📬 *Jobs applied today (via portal):* {jobs_applied_today}\n"

            if pipeline:
                msg += "\n📈 *Active Pipeline:*\n"
                for status in ["Applied", "Interview", "Offer"]:
                    if status in pipeline:
                        msg += f"• {status}: {pipeline[status]}\n"
            else:
                msg += "\n📈 *Active Pipeline:* No active applications\n"

            # Daily motivation
            if log and log.jobs_applied >= 3:
                msg += "\n🔥 Great hustle today! Keep the momentum going."
            elif log and log.jobs_applied >= 1:
                msg += "\n👍 Good start. Try to push for 3+ applications tomorrow."
            else:
                msg += "\n💪 Tomorrow is a new day. Set a target and crush it."

            await send_telegram_message(chat_id, msg)
            logger.info(f"Evening check-in sent to chat_id={chat_id}")

    except Exception as e:
        logger.error(f"Evening check-in failed: {e}", exc_info=True)
```

---

## Task F — MIDDAY CHECK TASK (2:00 PM IST)

Create file: `app/tasks/midday_check.py`

```python
"""Midday check task — sends a nudge at 2:00 PM IST if no activity logged."""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func

from app.config import get_settings
from app.models.daily_log import DailyLog
from app.models.job import Job
from app.models.user import User
from app.services.telegram_service import send_telegram_message
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def midday_check_task() -> None:
    """
    Runs at 2:00 PM IST (8:30 AM UTC) Mon-Sat.
    Sends a nudge if no activity has been logged yet today.
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id
    owner_email = settings.owner_email

    if not chat_id or not owner_email:
        logger.warning("Scheduler: owner_telegram_chat_id or owner_email not configured, skipping midday check")
        return

    today_ist = datetime.now(IST).date()
    logger.info(f"Midday check running for {today_ist}")

    try:
        async with get_task_session() as db:
            # Find owner user
            result = await db.execute(select(User).where(User.email == owner_email))
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"Scheduler: owner user not found for email {owner_email}")
                return

            # Check if daily log exists for today
            result = await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date == today_ist,
                )
            )
            log = result.scalar_one_or_none()

            # Check today's job applications
            result = await db.execute(
                select(func.count()).select_from(Job).where(
                    Job.user_id == user.id,
                    Job.applied_date == today_ist,
                    Job.is_deleted.is_(False),
                )
            )
            jobs_applied_today = result.scalar() or 0

            # Determine what to send
            has_log = log is not None
            has_any_activity = has_log and (
                log.jobs_applied > 0
                or log.connections_sent > 0
                or log.comments_made > 0
                or log.post_published
                or log.networking_calls > 0
                or log.referrals_asked > 0
            )

            if has_any_activity:
                msg = f"☀️ *Midday Check — {today_ist.strftime('%A, %b %d')}*\n\n"
                msg += "✅ You've been active today! Keep going.\n"
                msg += f"• Jobs applied: {log.jobs_applied}\n"
                msg += f"• Connections: {log.connections_sent}\n"
                msg += f"• Comments: {log.comments_made}\n"
                if jobs_applied_today > log.jobs_applied:
                    msg += f"• Jobs via portal today: {jobs_applied_today}\n"
                msg += "\n🎯 Afternoon push: aim for 2 more applications."
            else:
                msg = f"☀️ *Midday Check — {today_ist.strftime('%A, %b %d')}*\n\n"
                msg += "⚠️ No activity logged yet today.\n\n"
                msg += "Here's a quick checklist:\n"
                msg += "1️⃣ Apply to 3 jobs\n"
                msg += "2️⃣ Send 5 connection requests\n"
                msg += "3️⃣ Comment on 3 posts\n"
                msg += "4️⃣ Update Naukri profile\n"
                msg += "\nUse /log when you're done!"

            await send_telegram_message(chat_id, msg)
            logger.info(f"Midday check sent to chat_id={chat_id}")

    except Exception as e:
        logger.error(f"Midday check failed: {e}", exc_info=True)
```

---

## Task G — MODIFY `app/main.py`

Add scheduler start/stop to the existing lifespan context manager. The current lifespan is:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from .services.telegram_service import register_webhook
    from .config import get_settings

    settings = get_settings()
    if settings.telegram_bot_token and settings.app_url:
        webhook_url = f"{settings.app_url}/api/telegram/webhook"
        await register_webhook(webhook_url, settings.telegram_webhook_secret)
        logger.info(f"Telegram webhook registered: {webhook_url}")
    yield
```

Change it to:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from .services.telegram_service import register_webhook
    from .config import get_settings
    from .scheduler import start_scheduler, stop_scheduler

    settings = get_settings()
    if settings.telegram_bot_token and settings.app_url:
        webhook_url = f"{settings.app_url}/api/telegram/webhook"
        await register_webhook(webhook_url, settings.telegram_webhook_secret)
        logger.info(f"Telegram webhook registered: {webhook_url}")

    # Start background scheduler
    start_scheduler()

    yield

    # Shutdown scheduler gracefully
    stop_scheduler()
```

**Key**: The scheduler starts AFTER the webhook registration (so Telegram is ready to receive messages). It stops in the shutdown phase after `yield`.

---

## Task H — TELEGRAM TEST COMMANDS (`app/routers/telegram.py`)

Add two test commands so the scheduler can be tested on-demand via Telegram. Add them BEFORE the default "Unknown command" handler (line 210).

Find this block (around line 208-211):

```python
    await send_telegram_message(chat_id, "Daily log saved.")
    return {"ok": True}

    await send_telegram_message(chat_id, "Unknown command. Use /help.")
    return {"ok": True}
```

Insert these commands BETWEEN the `/log` handler's `return` and the default "Unknown command" line:

```python
    if command == "/test-evening":
        from app.tasks.evening_checkin import evening_checkin_task
        await evening_checkin_task()
        await send_telegram_message(chat_id, "Evening check-in task executed.")
        return {"ok": True}

    if command == "/test-midday":
        from app.tasks.midday_check import midday_check_task
        await midday_check_task()
        await send_telegram_message(chat_id, "Midday check task executed.")
        return {"ok": True}
```

Also update the `/help` response (line 57-60) to include the new commands. Add to the help text:
```
/test-evening\n/test-midday
```

**Note**: These test commands call the task functions directly (not through the scheduler). They require the user to be connected (the `user is None` check at line 78 still applies). The tasks themselves use `owner_email` from config to find the user, so the test commands will work regardless of which Telegram user triggers them.

---

## CRITICAL IMPLEMENTATION DETAILS

1. **APScheduler version**: Pin `>=3.10,<4.0`. Version 4.x has a completely different API (`AsyncScheduler` instead of `AsyncIOScheduler`, different `add_job` signature, etc.).

2. **IST timezone**: Always use `datetime.now(IST).date()` for "today in India". Never use `date.today()` or `datetime.utcnow().date()` — both will be wrong near midnight IST.

3. **Session management**: Scheduler tasks MUST create their own sessions via `get_task_session()`. Do NOT import or call `get_db()` from tasks — it's a FastAPI async generator dependency.

4. **Error handling**: Every task must wrap its entire body in `try/except`. An unhandled exception in a scheduler task will cause APScheduler to log it, but we want explicit error messages.

5. **Existing `send_telegram_message`**: Import from `app.services.telegram_service`. Do NOT create a new send function. It already handles message splitting (4096 char limit) and uses `parse_mode="Markdown"`.

6. **`misfire_grace_time`**: Set to 300 seconds (5 minutes). Railway can have brief downtime during deploys. Without this, a task that fires during a deploy would be permanently skipped.

7. **Lazy imports in scheduler**: `register_jobs()` uses lazy imports (`from app.tasks.xxx import ...`) to avoid circular import issues at module load time.

8. **Config defaults**: Both `owner_telegram_chat_id` (default 0) and `owner_email` (default "") have falsy defaults. Tasks check for these and skip gracefully if not configured.

---

## WHAT NOT TO CHANGE

- Do NOT modify `app/database.py` — use `AsyncSessionLocal` as-is
- Do NOT modify `app/services/telegram_service.py` — use existing `send_telegram_message()`
- Do NOT modify any model files
- Do NOT modify any schema files
- Do NOT create any Alembic migrations (no DB changes needed)
- Do NOT modify `app/dependencies.py` or `app/auth/`
- Do NOT use `@app.on_event("startup")` — the codebase uses `lifespan=`
- Do NOT use APScheduler 4.x API (no `AsyncScheduler`, no `RunState`)
- Do NOT use `datetime.utcnow()` — use `datetime.now(timezone.utc)` or `datetime.now(IST)`
- Do NOT use `date.today()` in tasks — use `datetime.now(IST).date()` for IST-aware dates

---

## Files to create (summary)

| File | Purpose |
|---|---|
| `app/scheduler.py` | APScheduler setup, job registration, start/stop functions |
| `app/tasks/__init__.py` | Empty — makes `tasks` a package |
| `app/tasks/db.py` | `get_task_session()` async context manager |
| `app/tasks/evening_checkin.py` | 6:30 PM IST daily summary task |
| `app/tasks/midday_check.py` | 2:00 PM IST midday nudge task |

## Files to modify (summary)

| File | Changes |
|---|---|
| `requirements.txt` | Add `APScheduler>=3.10,<4.0` |
| `app/config.py` | Add `owner_telegram_chat_id: int = 0` and `owner_email: str = ""` |
| `app/main.py` | Import and call `start_scheduler()` / `stop_scheduler()` in lifespan |
| `app/routers/telegram.py` | Add `/test-evening` and `/test-midday` commands before default handler, update `/help` text |

## Environment variables to set on Railway

```
OWNER_TELEGRAM_CHAT_ID=7019499883
OWNER_EMAIL=abhinav.jain.iitd@gmail.com
```
