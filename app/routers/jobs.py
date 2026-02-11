from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company
from app.models.contact import Contact
from app.models.job import Job
from app.models.profile import ProfileDNA
from app.schemas.jobs import JDAnalyzeRequest, JobCreate, JobOut, JobUpdate, PaginatedResponse
from app.services.ai_service import analyze_jd


router = APIRouter()


@router.get("", response_model=PaginatedResponse)
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    page: int = 1,
    per_page: int = 20,
    status: str | None = None,
    company_name: str | None = None,
    source_portal: str | None = None,
    sort: str = Query("-created_at"),
):
    base_query = select(Job).where(Job.user_id == current_user.id, Job.is_deleted.is_(False))
    if status:
        base_query = base_query.where(Job.status == status)
    if company_name:
        base_query = base_query.where(Job.company_name.ilike(f"%{company_name}%"))
    if source_portal:
        base_query = base_query.where(Job.source_portal == source_portal)
    if sort.startswith("-"):
        field = getattr(Job, sort[1:], Job.created_at)
        items_query = base_query.order_by(field.desc())
    else:
        field = getattr(Job, sort, Job.created_at)
        items_query = base_query.order_by(field.asc())

    # Simple total count with no GROUP BY / ORDER BY complications
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    offset = (page - 1) * per_page if per_page else 0
    items = (await db.execute(items_query.limit(per_page).offset(offset))).scalars().all()
    pages = (total + per_page - 1) // per_page if per_page else 1
    return PaginatedResponse(items=[JobOut.model_validate(i) for i in items], total=total, page=page, per_page=per_page, pages=pages)


@router.post("/", response_model=JobOut, status_code=201)
async def create_job(
    payload: JobCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> JobOut:
    # Deduplicate by company + role (case-insensitive) for this user
    existing = await db.execute(
        select(Job).where(
            Job.user_id == current_user.id,
            func.lower(Job.company_name) == func.lower(payload.company_name),
            func.lower(Job.role_title) == func.lower(payload.role_title),
            Job.is_deleted.is_(False),
        )
    )
    existing_job = existing.scalar_one_or_none()
    if existing_job is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Job already exists: {payload.company_name} - {payload.role_title}. Use PATCH /api/jobs/{{id}} to update.",
                "existing_id": str(existing_job.id),
            },
        )

    data = payload.model_dump(by_alias=False, exclude_unset=True)
    job = Job(
        user_id=current_user.id,
        company_name=data["company_name"],
        role_title=data["role_title"],
        jd_text=data.get("jd_text"),
        jd_url=data.get("jd_url"),
        source_portal=data.get("source_portal") or "Direct",
        status=data.get("status") or "Applied",
        fit_score=data.get("fit_score"),
        ats_score=data.get("ats_score"),
        resume_version=data.get("resume_version"),
        apply_type=data.get("apply_type"),
        referral_contact=data.get("referral_contact"),
        notes=data.get("notes"),
        applied_date=data.get("applied_date") or datetime.utcnow().date(),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return JobOut.model_validate(job)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)) -> JobOut:
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.model_validate(job)


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: str,
    payload: JobUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> JobOut:
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(job, field, value)

    await db.commit()
    await db.refresh(job)
    return JobOut.model_validate(job)


@router.delete("/{job_id}")
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)) -> dict:
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    job.is_deleted = True
    await db.commit()
    return {"status": "deleted"}


@router.get("/pipeline")
async def get_pipeline(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get comprehensive pipeline view with aggregations and actionable lists."""
    today = datetime.utcnow().date()
    
    # Get all active jobs for this user
    all_jobs = (
        await db.execute(
            select(Job)
            .where(Job.user_id == current_user.id, Job.is_deleted.is_(False))
            .order_by(Job.updated_at.desc())
        )
    ).scalars().all()
    
    # Build pipeline breakdown by status
    pipeline = {}
    for job in all_jobs:
        pipeline[job.status] = pipeline.get(job.status, 0) + 1
    
    # Calculate active count (excluding terminal states)
    inactive_statuses = {"Rejected", "Withdrawn", "Ghosted"}
    active_count = sum(count for status, count in pipeline.items() if status not in inactive_statuses)
    
    # Get recent 5 jobs (ordered by updated_at)
    recent = []
    for job in all_jobs[:5]:
        if job.updated_at:
            days_since = (today - job.updated_at.date()).days
        else:
            days_since = 0
        recent.append({
            "id": str(job.id),
            "company": job.company_name,
            "role": job.role_title,
            "status": job.status,
            "applied_date": job.applied_date.isoformat() if job.applied_date else None,
            "days_since_update": days_since,
        })
    
    # Find stale applications (Applied status, 14+ days since update)
    stale = []
    stale_threshold = today - timedelta(days=14)
    for job in all_jobs:
        if job.status == "Applied" and job.updated_at and job.updated_at.date() <= stale_threshold:
            days_since = (today - job.updated_at.date()).days
            stale.append({
                "id": str(job.id),
                "company": job.company_name,
                "role": job.role_title,
                "status": job.status,
                "applied_date": job.applied_date.isoformat() if job.applied_date else None,
                "days_since_update": days_since,
                "suggested_action": "Follow up or check for referral connection",
            })
    
    return {
        "pipeline": pipeline,
        "total": len(all_jobs),
        "active": active_count,
        "recent": recent,
        "stale": stale,
    }


@router.post("/analyze-jd")
async def analyze_jd_endpoint(
    payload: JDAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not (100 <= len(payload.jd_text) <= 15000):
        raise HTTPException(status_code=400, detail="jd_text must be between 100 and 15000 characters")

    prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = prof_res.scalar_one_or_none()
    profile_dict: dict[str, Any] = {}
    if profile is not None:
        profile_dict = {
            "full_name": profile.full_name,
            "positioning_statement": profile.positioning_statement,
            "target_roles": profile.target_roles,
            "core_skills": profile.core_skills,
            "tools_platforms": profile.tools_platforms,
            "industries": profile.industries,
            "experience_level": profile.experience_level,
            "years_of_experience": profile.years_of_experience,
        }

    analysis = await analyze_jd(payload.jd_text, profile_dict)
    if analysis is None:
        raise HTTPException(status_code=503, detail="AI analysis temporarily unavailable")

    company_name = analysis.get("company_name") or "Unknown Company"
    role_title = analysis.get("role_title") or "Unknown Role"

    # Check for existing job - upsert behavior
    existing = await db.execute(
        select(Job).where(
            Job.user_id == current_user.id,
            func.lower(Job.company_name) == func.lower(company_name),
            func.lower(Job.role_title) == func.lower(role_title),
            Job.is_deleted.is_(False),
        )
    )
    existing_job = existing.scalar_one_or_none()

    if existing_job:
        # Update existing job with new analysis
        existing_job.fit_score = analysis.get("fit_score")
        existing_job.ats_score = analysis.get("ats_score")
        existing_job.jd_text = payload.jd_text
        existing_job.jd_url = payload.jd_url
        existing_job.keywords_matched = analysis.get("keywords_matched")
        existing_job.keywords_missing = analysis.get("keywords_missing")
        existing_job.ai_analysis = analysis
        existing_job.source_portal = "JD Analysis"
        job = existing_job
    else:
        # Create new job
        job = Job(
            user_id=current_user.id,
            company_name=company_name,
            role_title=role_title,
            jd_text=payload.jd_text,
            jd_url=payload.jd_url,
            status="Analyzed",
            fit_score=analysis.get("fit_score"),
            ats_score=analysis.get("ats_score"),
            keywords_matched=analysis.get("keywords_matched"),
            keywords_missing=analysis.get("keywords_missing"),
            ai_analysis=analysis,
            source_portal="JD Analysis",
        )
        db.add(job)

    await db.commit()
    await db.refresh(job)

    return {"analysis": analysis, "job_id": str(job.id)}


@router.get("/search")
async def global_search(
    q: str,
    types: str = "jobs,companies,contacts",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    types_set = {t.strip() for t in types.split(",")}
    results: dict[str, list[dict[str, Any]]] = {"jobs": [], "companies": [], "contacts": []}

    like = f"%{q}%"

    if "jobs" in types_set:
        j_rows = (
            await db.execute(
                select(Job).where(
                    Job.user_id == current_user.id,
                    Job.is_deleted.is_(False),
                    or_(Job.company_name.ilike(like), Job.role_title.ilike(like)),
                )
            )
        ).scalars().all()
        results["jobs"] = [
            {"id": str(j.id), "company_name": j.company_name, "role_title": j.role_title, "status": j.status}
            for j in j_rows
        ]

    if "companies" in types_set:
        c_rows = (
            await db.execute(
                select(Company).where(
                    Company.user_id == current_user.id,
                    Company.name.ilike(like),
                )
            )
        ).scalars().all()
        results["companies"] = [
            {"id": str(c.id), "name": c.name, "lane": c.lane}
            for c in c_rows
        ]

    if "contacts" in types_set:
        ct_rows = (
            await db.execute(
                select(Contact).where(
                    Contact.user_id == current_user.id,
                    Contact.is_deleted.is_(False),
                    or_(Contact.name.ilike(like), Contact.company.ilike(like)),
                )
            )
        ).scalars().all()
        results["contacts"] = [
            {"id": str(c.id), "name": c.name, "company": c.company}
            for c in ct_rows
        ]

    return results
