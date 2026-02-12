"""Scout results API endpoints."""
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.job import Job
from app.models.scout_result import ScoutResult
from app.schemas.scout import ScoutResultOut, ScoutResultsPage, ScoutRunSummary
from app.services.scout_service import run_scout

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/results", response_model=ScoutResultsPage)
async def list_scout_results(
    status: str | None = Query(None, description="Filter by status: new, reviewed, promoted, dismissed"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List scout results with optional status filter."""
    query = select(ScoutResult).where(
        ScoutResult.user_id == current_user.id,
    ).order_by(ScoutResult.created_at.desc())

    if status:
        query = query.where(ScoutResult.status == status)

    # Count total
    count_query = select(func.count()).select_from(
        query.subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()

    return ScoutResultsPage(
        items=[ScoutResultOut.model_validate(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/run", response_model=ScoutRunSummary)
async def trigger_scout_run(
    current_user=Depends(get_current_user),
):
    """Manually trigger a scout run for the current user."""
    summary = await run_scout(user_id=str(current_user.id))
    return ScoutRunSummary(**summary)


@router.post("/results/{scout_id}/promote")
async def promote_scout_result(
    scout_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Manually promote a scout result to the jobs pipeline."""
    result = await db.execute(
        select(ScoutResult).where(
            ScoutResult.id == scout_id,
            ScoutResult.user_id == current_user.id,
        )
    )
    scout_result = result.scalar_one_or_none()
    if not scout_result:
        raise HTTPException(status_code=404, detail="Scout result not found")

    if scout_result.status == "promoted":
        raise HTTPException(status_code=400, detail="Already promoted")

    # Create job in pipeline
    new_job = Job(
        user_id=current_user.id,
        company_name=(scout_result.company_name or "Unknown")[:255],
        role_title=(scout_result.title or "Unknown")[:255],
        source_portal=(scout_result.source or "scout")[:100],
        jd_url=scout_result.source_url[:1000] if scout_result.source_url else None,
        jd_text=scout_result.snippet,
        status="Tracking",
        fit_score=scout_result.fit_score,
        fit_reasoning=scout_result.ai_reasoning,
        salary_range=scout_result.salary_raw,
        notes=[{
            "text": f"Manually promoted from Scout. Fit score: {scout_result.fit_score or 'N/A'}/10.",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "type": "scout",
        }],
    )
    db.add(new_job)
    await db.flush()

    scout_result.status = "promoted"
    scout_result.promoted_job_id = new_job.id

    await db.commit()
    await db.refresh(new_job)

    return {"status": "promoted", "job_id": str(new_job.id)}


@router.post("/results/{scout_id}/dismiss")
async def dismiss_scout_result(
    scout_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mark a scout result as dismissed (not relevant)."""
    result = await db.execute(
        select(ScoutResult).where(
            ScoutResult.id == scout_id,
            ScoutResult.user_id == current_user.id,
        )
    )
    scout_result = result.scalar_one_or_none()
    if not scout_result:
        raise HTTPException(status_code=404, detail="Scout result not found")

    scout_result.status = "dismissed"
    await db.commit()

    return {"status": "dismissed"}
