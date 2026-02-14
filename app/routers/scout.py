"""Scout API endpoints: job scouting preferences, scouted jobs, and legacy scout results."""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.job import Job
from app.models.scout import ScoutedJob, UserScoutPreferences, UserScoutedJob
from app.models.scout_result import ScoutResult
from app.schemas.jobs import JobOut
from app.schemas.scout import (
    DismissRequest,
    ScoutedJobDetails,
    ScoutResultOut,
    ScoutResultsPage,
    ScoutRunSummary,
    ScoutStatsOut,
    UserScoutedJobOut,
    UserScoutPreferencesOut,
    UserScoutPreferencesUpdate,
)
from app.services.scout_preferences import (
    get_or_create_preferences,
    sync_preferences_from_profile,
    update_learned_preferences,
)
from app.services.scout_service import run_scout
from app.tasks.job_scout import run_job_scout

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Job scouting preferences ---

@router.get("/preferences", response_model=UserScoutPreferencesOut, status_code=200)
async def get_scout_preferences(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Get user's scout preferences. Auto-create from profile_dna if missing.

    **Response:** UserScoutPreferencesOut
    **Errors:** 401 (unauthorized)
    """
    prefs = await get_or_create_preferences(db, current_user.id)
    return UserScoutPreferencesOut.model_validate(prefs)


@router.put("/preferences", response_model=UserScoutPreferencesOut, status_code=200)
async def update_scout_preferences(
    payload: UserScoutPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Update user's scout preferences.

    **Request:** UserScoutPreferencesUpdate
    **Response:** UserScoutPreferencesOut
    **Errors:** 401 (unauthorized)
    """
    prefs = await get_or_create_preferences(db, current_user.id)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(prefs, key, value)
    await db.commit()
    await db.refresh(prefs)
    return UserScoutPreferencesOut.model_validate(prefs)


@router.post("/preferences/sync-from-profile", response_model=UserScoutPreferencesOut, status_code=200)
async def sync_preferences_from_profile_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Sync scout preferences from profile_dna.

    **Response:** UserScoutPreferencesOut
    **Errors:** 401 (unauthorized)
    """
    synced = await sync_preferences_from_profile(db, current_user.id)
    if synced is None:
        # No preferences exist - create from profile
        prefs = await get_or_create_preferences(db, current_user.id)
        return UserScoutPreferencesOut.model_validate(prefs)
    return UserScoutPreferencesOut.model_validate(synced)


# --- Scouted jobs ---

@router.get("/jobs", status_code=200)
async def get_scouted_jobs(
    status: Optional[str] = Query(None, description="Filter: new, viewed, saved, dismissed"),
    min_score: int = Query(30, ge=0, description="Minimum relevance score"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Get scouted jobs with filtering. Paginated.

    **Query params:** status, min_score, limit, offset
    **Response:** {items: [...], total, limit, offset}
    **Errors:** 401 (unauthorized)
    """
    query = (
        select(UserScoutedJob)
        .where(
            UserScoutedJob.user_id == current_user.id,
            UserScoutedJob.relevance_score >= min_score,
        )
        .order_by(UserScoutedJob.matched_at.desc())
    )
    if status:
        query = query.where(UserScoutedJob.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one() or 0

    query = query.offset(offset).limit(limit)
    result = await db.execute(
        query.options(selectinload(UserScoutedJob.scouted_job))
    )
    rows = result.unique().scalars().all()

    items = []
    for usj in rows:
        job = usj.scouted_job
        if job is None:
            continue
        job_details = ScoutedJobDetails.model_validate(job)
        out = UserScoutedJobOut(
            id=usj.id,
            user_id=usj.user_id,
            scouted_job_id=usj.scouted_job_id,
            relevance_score=usj.relevance_score,
            score_breakdown=usj.score_breakdown,
            match_reasons=usj.match_reasons,
            status=usj.status,
            matched_at=usj.matched_at,
            viewed_at=usj.viewed_at,
            saved_at=usj.saved_at,
            dismissed_at=usj.dismissed_at,
            dismiss_reason=usj.dismiss_reason,
            pipeline_job_id=usj.pipeline_job_id,
            added_to_pipeline_at=usj.added_to_pipeline_at,
            created_at=usj.created_at,
            updated_at=usj.updated_at,
            job=job_details,
        )
        items.append(out)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/jobs/{scouted_job_id}/view", status_code=200)
async def mark_job_viewed(
    scouted_job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Mark scouted job as viewed.

    **Response:** {status: "success"}
    **Errors:** 404 (scouted job not found), 401 (unauthorized)
    """
    result = await db.execute(
        select(UserScoutedJob).where(
            UserScoutedJob.id == scouted_job_id,
            UserScoutedJob.user_id == current_user.id,
        )
    )
    usj = result.scalar_one_or_none()
    if not usj:
        raise HTTPException(status_code=404, detail="Scouted job not found")

    usj.status = "viewed"
    usj.viewed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "success"}


@router.post("/jobs/{scouted_job_id}/save", status_code=200)
async def save_job(
    scouted_job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Save scouted job for later.

    **Response:** {status: "success"}
    **Errors:** 404 (scouted job not found), 401 (unauthorized)
    """
    result = await db.execute(
        select(UserScoutedJob).where(
            UserScoutedJob.id == scouted_job_id,
            UserScoutedJob.user_id == current_user.id,
        )
    )
    usj = result.scalar_one_or_none()
    if not usj:
        raise HTTPException(status_code=404, detail="Scouted job not found")

    usj.status = "saved"
    usj.saved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "success"}


@router.post("/jobs/{scouted_job_id}/dismiss", status_code=200)
async def dismiss_job(
    scouted_job_id: UUID,
    body: DismissRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Dismiss scouted job with reason. Applies learning to preferences.

    **Request:** DismissRequest (reason)
    **Response:** {status: "success"}
    **Errors:** 404 (scouted job not found), 401 (unauthorized)
    """
    result = await db.execute(
        select(UserScoutedJob)
        .where(
            UserScoutedJob.id == scouted_job_id,
            UserScoutedJob.user_id == current_user.id,
        )
        .options(selectinload(UserScoutedJob.scouted_job))
    )
    usj = result.scalar_one_or_none()
    if not usj:
        raise HTTPException(status_code=404, detail="Scouted job not found")

    usj.status = "dismissed"
    usj.dismissed_at = datetime.now(timezone.utc)
    usj.dismiss_reason = body.reason

    # Apply learning
    if usj.scouted_job:
        await update_learned_preferences(
            db, current_user.id, body.reason, usj.scouted_job
        )
    else:
        await db.commit()

    return {"status": "success"}


@router.post("/jobs/{scouted_job_id}/to-pipeline", response_model=JobOut, status_code=201)
async def add_job_to_pipeline(
    scouted_job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Add scouted job to main jobs pipeline.

    **Response:** JobOut
    **Errors:** 400 (already in pipeline), 404 (scouted job not found), 401 (unauthorized)
    """
    result = await db.execute(
        select(UserScoutedJob)
        .where(
            UserScoutedJob.id == scouted_job_id,
            UserScoutedJob.user_id == current_user.id,
        )
        .options(selectinload(UserScoutedJob.scouted_job))
    )
    usj = result.scalar_one_or_none()
    if not usj:
        raise HTTPException(status_code=404, detail="Scouted job not found")

    if usj.pipeline_job_id:
        raise HTTPException(
            status_code=400,
            detail="Job already added to pipeline",
        )

    job = usj.scouted_job
    if not job:
        raise HTTPException(status_code=404, detail="Scouted job data not found")

    salary_range = None
    if job.salary_min or job.salary_max:
        parts = []
        if job.salary_min:
            parts.append(f"{job.salary_min // 100_000}L")
        if job.salary_max:
            parts.append(f"{job.salary_max // 100_000}L")
        salary_range = "-".join(parts) if parts else None

    new_job = Job(
        user_id=current_user.id,
        company_name=(job.company_name or "Unknown")[:255],
        role_title=(job.title or "Unknown")[:255],
        source_portal=(job.source or "scout")[:100],
        jd_url=job.source_url[:1000] if job.source_url else None,
        jd_text=job.description,
        status="Tracking",
        fit_score=usj.relevance_score / 10.0 if usj.relevance_score else None,
        fit_reasoning="; ".join(usj.match_reasons) if usj.match_reasons else None,
        salary_range=salary_range,
        notes=[
            {
                "text": f"Added from Scout. Score: {usj.relevance_score}/100. Reasons: {', '.join(usj.match_reasons or [])}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "type": "scout",
            }
        ],
    )
    db.add(new_job)
    await db.flush()

    usj.pipeline_job_id = new_job.id
    usj.added_to_pipeline_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(new_job)

    return JobOut.model_validate(new_job)


@router.get("/stats", response_model=ScoutStatsOut, status_code=200)
async def get_scout_stats(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Get scout stats (new, viewed, saved, dismissed, added_to_pipeline counts).

    **Response:** ScoutStatsOut
    **Errors:** 401 (unauthorized)
    """
    base = select(UserScoutedJob).where(UserScoutedJob.user_id == current_user.id)

    async def _count(cond):
        q = select(func.count()).select_from(base.where(cond).subquery())
        r = await db.execute(q)
        return r.scalar_one() or 0

    new_count = await _count(UserScoutedJob.status == "new")
    viewed_count = await _count(UserScoutedJob.status == "viewed")
    saved_count = await _count(UserScoutedJob.status == "saved")
    dismissed_count = await _count(UserScoutedJob.status == "dismissed")
    added_to_pipeline_count = await _count(UserScoutedJob.pipeline_job_id.isnot(None))

    return ScoutStatsOut(
        new_count=new_count,
        viewed_count=viewed_count,
        saved_count=saved_count,
        dismissed_count=dismissed_count,
        added_to_pipeline_count=added_to_pipeline_count,
    )


# --- Legacy scout results (ScoutResult model) ---

@router.get("/results", response_model=ScoutResultsPage, status_code=200)
async def list_scout_results(
    status: Optional[str] = Query(None, description="Filter by status: new, reviewed, promoted, dismissed"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    List legacy scout results with optional status filter.

    **Query params:** status, page, per_page
    **Response:** ScoutResultsPage
    **Errors:** 401 (unauthorized)
    """
    query = select(ScoutResult).where(
        ScoutResult.user_id == current_user.id,
    ).order_by(ScoutResult.created_at.desc())

    if status:
        query = query.where(ScoutResult.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one() or 0

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()

    return ScoutResultsPage(
        items=[ScoutResultOut.model_validate(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/run", response_model=ScoutRunSummary, status_code=200)
async def trigger_scout_run(
    current_user=Depends(get_current_user),
):
    """
    Manually trigger a scout run for the current user.

    **Response:** ScoutRunSummary
    **Errors:** 401 (unauthorized)
    """
    summary = await run_scout(user_id=str(current_user.id))
    return ScoutRunSummary(**summary)


@router.post("/results/{scout_id}/promote", status_code=200)
async def promote_scout_result(
    scout_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Promote legacy scout result to jobs pipeline.

    **Response:** {status: "promoted", job_id: str}
    **Errors:** 400 (already promoted), 404 (not found), 401 (unauthorized)
    """
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
        notes=[
            {
                "text": f"Manually promoted from Scout. Fit score: {scout_result.fit_score or 'N/A'}/10.",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "type": "scout",
            }
        ],
    )
    db.add(new_job)
    await db.flush()

    scout_result.status = "promoted"
    scout_result.promoted_job_id = new_job.id

    await db.commit()
    await db.refresh(new_job)

    return {"status": "promoted", "job_id": str(new_job.id)}


@router.post("/results/{scout_id}/dismiss", status_code=200)
async def dismiss_scout_result(
    scout_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Mark legacy scout result as dismissed.

    **Response:** {status: "dismissed"}
    **Errors:** 404 (not found), 401 (unauthorized)
    """
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


@router.post("/run-now", status_code=200)
async def run_now(
    current_user=Depends(get_current_user),
):
    """
    Manually trigger job scout task (SerpAPI fetch, upsert, matching).

    **Response:** {status: "completed", result: {...}}
    **Errors:** 401 (unauthorized)
    """
    result = await run_job_scout()
    return {"status": "completed", "result": result}
