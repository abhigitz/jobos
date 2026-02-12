from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.activity_log import ActivityLog


router = APIRouter()


@router.get("")
async def get_activity_log(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get recent activity for current user."""
    result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.user_id == current_user.id)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
    )
    activities = result.scalars().all()

    return [
        {
            "id": str(a.id),
            "action_type": a.action_type,
            "description": a.description,
            "related_job_id": str(a.related_job_id) if a.related_job_id else None,
            "related_contact_id": str(a.related_contact_id) if a.related_contact_id else None,
            "created_at": a.created_at.isoformat(),
        }
        for a in activities
    ]
