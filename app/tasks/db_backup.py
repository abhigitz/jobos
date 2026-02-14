"""Daily database backup task.

On Railway: verifies DB connection and logs that Railway manages backups.
Locally: exports critical tables to JSON (no pg_dump required).
"""
import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import (
    Company,
    Contact,
    Job,
    ScoutedJob,
    User,
    UserScoutPreferences,
    UserScoutedJob,
)

logger = logging.getLogger(__name__)

BACKUP_DIR = Path("/tmp")


def _serialize_value(val: Any) -> Any:
    """Convert non-JSON-serializable values for export."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if hasattr(val, "hex"):  # UUID
        return str(val)
    if isinstance(val, list):
        return [_serialize_value(v) for v in val]
    if isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    return val


def _model_to_dict(instance: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    """Convert SQLAlchemy model instance to JSON-serializable dict."""
    exclude = exclude or set()
    result: dict[str, Any] = {}
    for col in instance.__table__.columns:
        if col.key in exclude:
            continue
        val = getattr(instance, col.key)
        result[col.key] = _serialize_value(val)
    return result


async def _export_tables_to_json(backup_path: Path) -> dict[str, int]:
    """Export critical tables to a single JSON file. Returns row counts per table."""
    counts: dict[str, int] = {}
    data: dict[str, list[dict[str, Any]]] = {}

    async with AsyncSessionLocal() as db:
        # Users (excluding hashed_password)
        try:
            result = await db.execute(select(User))
            users = result.scalars().all()
            data["users"] = [_model_to_dict(u, exclude={"hashed_password"}) for u in users]
            counts["users"] = len(users)
        except Exception as e:
            logger.error("Failed to export users: %s", e)
            raise

        # Jobs
        try:
            result = await db.execute(select(Job))
            jobs = result.scalars().all()
            data["jobs"] = [_model_to_dict(j) for j in jobs]
            counts["jobs"] = len(jobs)
        except Exception as e:
            logger.error("Failed to export jobs: %s", e)
            raise

        # Companies
        try:
            result = await db.execute(select(Company))
            companies = result.scalars().all()
            data["companies"] = [_model_to_dict(c) for c in companies]
            counts["companies"] = len(companies)
        except Exception as e:
            logger.error("Failed to export companies: %s", e)
            raise

        # Contacts
        try:
            result = await db.execute(select(Contact))
            contacts = result.scalars().all()
            data["contacts"] = [_model_to_dict(c) for c in contacts]
            counts["contacts"] = len(contacts)
        except Exception as e:
            logger.error("Failed to export contacts: %s", e)
            raise

        # User scout preferences
        try:
            result = await db.execute(select(UserScoutPreferences))
            prefs = result.scalars().all()
            data["user_scout_preferences"] = [_model_to_dict(p) for p in prefs]
            counts["user_scout_preferences"] = len(prefs)
        except Exception as e:
            logger.error("Failed to export user_scout_preferences: %s", e)
            raise

        # Scouted jobs
        try:
            result = await db.execute(select(ScoutedJob))
            jobs = result.scalars().all()
            data["scouted_jobs"] = [_model_to_dict(j) for j in jobs]
            counts["scouted_jobs"] = len(jobs)
        except Exception as e:
            logger.error("Failed to export scouted_jobs: %s", e)
            raise

        # User scouted jobs
        try:
            result = await db.execute(select(UserScoutedJob))
            uj = result.scalars().all()
            data["user_scouted_jobs"] = [_model_to_dict(u) for u in uj]
            counts["user_scouted_jobs"] = len(uj)
        except Exception as e:
            logger.error("Failed to export user_scouted_jobs: %s", e)
            raise

    with open(backup_path, "w") as f:
        json.dump(data, f, indent=2, default=str)

    return counts


async def _verify_db_connection(db: AsyncSession) -> bool:
    """Verify database connection is working."""
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("DB connection check failed: %s", e)
        return False


async def _notify_telegram(status: str, message: str) -> None:
    """Send backup status notification to owner via Telegram."""
    try:
        settings = get_settings()
        if settings.telegram_bot_token and settings.owner_telegram_chat_id:
            from app.services.telegram_service import send_telegram_message

            if status == "success":
                emoji = "✅"
            elif status == "skip":
                emoji = "ℹ️"
            else:
                emoji = "⚠️"
            msg = f"{emoji} *JobOS Backup*\n\n{message[:500]}"
            await send_telegram_message(settings.owner_telegram_chat_id, msg)
    except Exception as e:
        logger.warning("Could not send Telegram notification: %s", e)


async def run_daily_backup() -> dict:
    """Run daily backup. On Railway: verify DB only. Locally: export tables to JSON."""
    is_railway = bool(os.environ.get("RAILWAY_ENVIRONMENT"))

    try:
        async with AsyncSessionLocal() as db:
            if not await _verify_db_connection(db):
                await _notify_telegram("fail", "Database connection verification failed.")
                return {"success": False, "error": "DB connection failed"}

        if is_railway:
            logger.info("Railway manages backups. DB connection verified.")
            await _notify_telegram("skip", "Railway manages backups. DB connection verified.")
            return {
                "success": True,
                "mode": "railway",
                "message": "Railway manages backups",
            }

        # Local: export critical tables to JSON
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"jobos_backup_{timestamp}.json"

        try:
            counts = await _export_tables_to_json(backup_path)
        except Exception as e:
            logger.error("JSON export failed: %s", e, exc_info=True)
            await _notify_telegram("fail", f"Backup export failed: {str(e)[:400]}")
            return {"success": False, "error": str(e)}

        file_size = backup_path.stat().st_size
        total_rows = sum(counts.values())
        summary = ", ".join(f"{k}: {v}" for k, v in counts.items())

        logger.info(
            "Backup created: %s (%.1f KB, %d rows)",
            backup_path.name,
            file_size / 1024,
            total_rows,
        )

        await _notify_telegram(
            "success",
            f"Backup created: {backup_path.name}\n{total_rows} rows\n{summary}",
        )

        return {
            "success": True,
            "mode": "local",
            "file": backup_path.name,
            "size_kb": round(file_size / 1024, 1),
            "row_counts": counts,
            "total_rows": total_rows,
        }

    except Exception as e:
        logger.error("Backup error: %s", str(e), exc_info=True)
        await _notify_telegram("fail", f"Backup error: {str(e)[:400]}")
        return {"success": False, "error": str(e)}
