"""Cloudflare R2 database backup task.

Exports critical tables to JSON, compresses with gzip, and uploads to R2.
"""
import gzip
import json
import logging
import os
import re
from datetime import datetime
from typing import Any
from uuid import UUID

import boto3
from botocore.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import (
    Company,
    Contact,
    Job,
    ResumeFile,
    ScoutedJob,
    User,
    UserScoutPreferences,
    UserScoutedJob,
)

logger = logging.getLogger(__name__)

# R2 env vars
R2_ENDPOINT_URL = "R2_ENDPOINT_URL"
R2_ACCESS_KEY_ID = "R2_ACCESS_KEY_ID"
R2_SECRET_ACCESS_KEY = "R2_SECRET_ACCESS_KEY"
R2_BUCKET_NAME = "R2_BUCKET_NAME"


def get_r2_client():
    """Create boto3 S3 client for Cloudflare R2."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get(R2_ENDPOINT_URL),
        aws_access_key_id=os.environ.get(R2_ACCESS_KEY_ID),
        aws_secret_access_key=os.environ.get(R2_SECRET_ACCESS_KEY),
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def serialize_value(value: Any) -> Any:
    """Convert non-JSON-serializable values for export."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value


def model_to_dict(model_instance: Any) -> dict:
    """Convert SQLAlchemy model to dict. Skips keys starting with '_'."""
    result = {}
    for col in model_instance.__table__.columns:
        key = col.key
        if key.startswith("_"):
            continue
        val = getattr(model_instance, key)
        result[key] = serialize_value(val)
    return result


async def export_tables_to_json(db: AsyncSession) -> dict:
    """Export all backup tables to a JSON-serializable dict."""
    tables_data = {}
    counts = {}

    # users (exclude password_hash / hashed_password from output)
    result = await db.execute(select(User))
    users = result.scalars().all()
    user_dicts = [model_to_dict(u) for u in users]
    for d in user_dicts:
        d.pop("password_hash", None)
        d.pop("hashed_password", None)
    tables_data["users"] = user_dicts
    counts["users"] = len(users)

    # jobs
    result = await db.execute(select(Job))
    jobs = result.scalars().all()
    tables_data["jobs"] = [model_to_dict(j) for j in jobs]
    counts["jobs"] = len(jobs)

    # companies
    result = await db.execute(select(Company))
    companies = result.scalars().all()
    tables_data["companies"] = [model_to_dict(c) for c in companies]
    counts["companies"] = len(companies)

    # contacts
    result = await db.execute(select(Contact))
    contacts = result.scalars().all()
    tables_data["contacts"] = [model_to_dict(c) for c in contacts]
    counts["contacts"] = len(contacts)

    # resumes (ResumeFile model)
    result = await db.execute(select(ResumeFile))
    resumes = result.scalars().all()
    tables_data["resumes"] = [model_to_dict(r) for r in resumes]
    counts["resumes"] = len(resumes)

    # user_scout_preferences
    result = await db.execute(select(UserScoutPreferences))
    prefs = result.scalars().all()
    tables_data["user_scout_preferences"] = [model_to_dict(p) for p in prefs]
    counts["user_scout_preferences"] = len(prefs)

    # scouted_jobs
    result = await db.execute(select(ScoutedJob))
    scouted = result.scalars().all()
    tables_data["scouted_jobs"] = [model_to_dict(j) for j in scouted]
    counts["scouted_jobs"] = len(scouted)

    # user_scouted_jobs
    result = await db.execute(select(UserScoutedJob))
    user_scouted = result.scalars().all()
    tables_data["user_scouted_jobs"] = [model_to_dict(u) for u in user_scouted]
    counts["user_scouted_jobs"] = len(user_scouted)

    return {
        "exported_at": datetime.utcnow().isoformat(),
        "tables": tables_data,
        "counts": counts,
    }


def upload_to_r2(data: bytes, filename: str) -> bool:
    """Upload data to R2 bucket. Returns True on success, False on failure."""
    try:
        client = get_r2_client()
        bucket = os.environ.get(R2_BUCKET_NAME)
        if not bucket:
            logger.error("R2_BUCKET_NAME not set")
            return False
        client.put_object(Bucket=bucket, Key=filename, Body=data)
        return True
    except Exception as e:
        logger.error("R2 upload failed: %s", e, exc_info=True)
        return False


async def backup_database() -> None:
    """Export DB to JSON, compress, upload to R2, and notify via Telegram."""
    required = [R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]
    if not all(os.environ.get(k) for k in required):
        from app.config import get_settings
        from app.services.telegram_service import send_telegram_message

        settings = get_settings()
        if settings.telegram_bot_token and settings.owner_telegram_chat_id:
            await send_telegram_message(
                settings.owner_telegram_chat_id,
                "⚠️ JobOS Backup Skipped - R2 credentials not configured",
            )
        return

    db = None
    try:
        async with AsyncSessionLocal() as db:
            data = await export_tables_to_json(db)

        json_str = json.dumps(data, indent=2, default=str)
        json_bytes = json_str.encode("utf-8")
        compressed_data = gzip.compress(json_bytes)

        filename = f"jobos_backup_{datetime.utcnow().strftime('%Y-%m-%d_%H-%M')}.json.gz"

        if not upload_to_r2(compressed_data, filename):
            raise RuntimeError("R2 upload failed")

        size_kb = len(compressed_data) / 1024
        counts = data["counts"]
        counts_str = ", ".join(f"{k}({v})" for k, v in counts.items())

        from app.config import get_settings
        from app.services.telegram_service import send_telegram_message

        settings = get_settings()
        msg = f"""✅ JobOS Backup Complete
📁 File: {filename}
📊 Size: {size_kb:.1f} KB
📋 Tables: {counts_str}
☁️ Stored in: Cloudflare R2"""

        if settings.telegram_bot_token and settings.owner_telegram_chat_id:
            await send_telegram_message(settings.owner_telegram_chat_id, msg)

    except Exception as e:
        logger.error("Backup failed: %s", e, exc_info=True)
        from app.config import get_settings
        from app.services.telegram_service import send_telegram_message

        settings = get_settings()
        if settings.telegram_bot_token and settings.owner_telegram_chat_id:
            await send_telegram_message(
                settings.owner_telegram_chat_id,
                f"❌ JobOS Backup Failed: {str(e)}",
            )


def cleanup_old_backups(keep_days: int = 30, keep_minimum: int = 7) -> None:
    """Delete backup files older than keep_days, but always keep at least keep_minimum."""
    if not all(os.environ.get(k) for k in [R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        return

    try:
        client = get_r2_client()
        bucket = os.environ.get(R2_BUCKET_NAME)
        if not bucket:
            return

        response = client.list_objects_v2(Bucket=bucket)
        objects = response.get("Contents", [])
        if not objects:
            return

        # Parse dates from filenames: jobos_backup_YYYY-MM-DD_HH-MM.json.gz
        pattern = re.compile(r"jobos_backup_(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}\.json\.gz")
        dated = []
        for obj in objects:
            key = obj.get("Key", "")
            m = pattern.match(key)
            if m:
                try:
                    dt = datetime.strptime(m.group(1), "%Y-%m-%d")
                    dated.append((dt, key, obj))
                except ValueError:
                    pass

        dated.sort(key=lambda x: x[0], reverse=True)

        cutoff = datetime.utcnow()
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=keep_days)

        to_delete = []
        kept = 0
        for dt, key, obj in dated:
            if kept < keep_minimum:
                kept += 1
                continue
            if dt < cutoff:
                to_delete.append({"Key": key})

        for item in to_delete:
            client.delete_object(Bucket=bucket, Key=item["Key"])
            logger.info("Deleted old backup: %s", item["Key"])

    except Exception as e:
        logger.error("Cleanup old backups failed: %s", e, exc_info=True)


# Legacy entry point for scheduler compatibility
async def run_daily_backup() -> dict:
    """Run daily backup. Uses R2 if configured, otherwise skips."""
    await backup_database()
    return {"success": True, "mode": "r2"}
