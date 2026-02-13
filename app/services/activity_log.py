from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog


async def log_activity(
    db: AsyncSession,
    user_id: UUID,
    action_type: str,
    description: str,
    related_job_id: UUID | None = None,
    related_contact_id: UUID | None = None,
) -> None:
    entry = ActivityLog(
        user_id=user_id,
        action_type=action_type,
        description=description,
        related_job_id=related_job_id,
        related_contact_id=related_contact_id,
    )
    db.add(entry)
    await db.commit()
