"""Admin-only endpoints."""
from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import get_settings

router = APIRouter()


async def verify_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Verify request has valid admin API key."""
    settings = get_settings()
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="Admin API not configured")
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return True


@router.post("/backup", dependencies=[Depends(verify_admin_key)])
async def trigger_backup():
    """Manually trigger database backup (admin only). Requires X-Admin-Key header."""
    from app.tasks.db_backup import run_daily_backup

    result = await run_daily_backup()
    return result
