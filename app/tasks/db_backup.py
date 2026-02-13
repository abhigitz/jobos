"""Daily database backup task using pg_dump."""
import asyncio
import logging
from datetime import datetime

from app.config import get_settings

logger = logging.getLogger(__name__)


async def run_backup() -> dict:
    """Daily database backup to local file."""
    try:
        settings = get_settings()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"/tmp/jobos_backup_{timestamp}.sql"

        # pg_dump needs standard postgresql:// URL (not postgresql+asyncpg://)
        db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            db_url,
            "-f",
            backup_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("Backup timed out after 5 minutes")
            return {"status": "error", "message": "Backup timed out"}

        if proc.returncode == 0:
            logger.info("Backup successful: %s", backup_file)
            # TODO: Upload to S3/GCS for persistence
            return {"status": "success", "file": backup_file}
        else:
            err_msg = stderr.decode() if stderr else "Unknown error"
            logger.error("Backup failed: %s", err_msg)
            return {"status": "error", "message": err_msg}

    except Exception as e:
        logger.error("Backup exception: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}
