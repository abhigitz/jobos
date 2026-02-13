"""Daily database backup task using pg_dump."""
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

# Use /app/backups on Railway (mount volume at /app/backups for persistence).
# Override with BACKUP_DIR env. Falls back to project backups/ for local dev.
_DEFAULT_BACKUP_DIR = (
    Path("/app/backups")
    if Path("/app").exists()
    else Path(__file__).resolve().parent.parent.parent / "backups"
)
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(_DEFAULT_BACKUP_DIR)))
MAX_BACKUPS = 7  # Keep 7 days of backups


async def run_daily_backup() -> dict:
    """Create PostgreSQL backup and cleanup old backups."""
    try:
        # Ensure backup directory exists
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

        # Generate backup filename with timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUP_DIR / f"jobos_backup_{timestamp}.sql"

        settings = get_settings()
        # pg_dump needs standard postgresql:// URL (not postgresql+asyncpg://)
        db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            db_url,
            "-f",
            str(backup_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("Backup timed out after 5 minutes")
            await _notify_telegram_on_failure("Backup timed out after 5 minutes")
            return {"success": False, "error": "Timeout"}

        if proc.returncode != 0:
            err_msg = stderr.decode() if stderr else "Unknown error"
            logger.error("Backup failed: %s", err_msg)
            await _notify_telegram_on_failure(err_msg)
            return {"success": False, "error": err_msg}

        # Get backup file size
        file_size = backup_file.stat().st_size
        logger.info("Backup created: %s (%.1f KB)", backup_file.name, file_size / 1024)

        # Cleanup old backups (keep last MAX_BACKUPS)
        backups = sorted(BACKUP_DIR.glob("jobos_backup_*.sql"))
        if len(backups) > MAX_BACKUPS:
            for old_backup in backups[:-MAX_BACKUPS]:
                old_backup.unlink()
                logger.info("Deleted old backup: %s", old_backup.name)

        return {
            "success": True,
            "file": backup_file.name,
            "size_kb": round(file_size / 1024, 1),
            "backups_retained": min(len(backups), MAX_BACKUPS),
        }

    except Exception as e:
        logger.error("Backup error: %s", str(e), exc_info=True)
        await _notify_telegram_on_failure(str(e))
        return {"success": False, "error": str(e)}


async def _notify_telegram_on_failure(error_msg: str) -> None:
    """Optionally notify owner via Telegram on backup failure."""
    try:
        settings = get_settings()
        if settings.telegram_bot_token and settings.owner_telegram_chat_id:
            from app.services.telegram_service import send_telegram_message

            msg = f"⚠️ *JobOS Backup Failed*\n\n{error_msg[:500]}"
            await send_telegram_message(settings.owner_telegram_chat_id, msg)
    except Exception as e:
        logger.warning("Could not send Telegram notification: %s", e)
