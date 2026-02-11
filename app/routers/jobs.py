from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company
from app.models.contact import Contact
from app.models.interview import Interview
from app.models.job import Job
from app.models.profile import ProfileDNA
from app.schemas.jobs import AddNoteRequest, JDAnalyzeRequest, JobCreate, JobOut, JobUpdate, NoteEntry, PaginatedResponse
from app.services.activity_log import log_activity
from app.services.ai_service import analyze_jd, call_claude


router = APIRouter()


# --- Pydantic schemas for new endpoints ---

class InterviewCreate(BaseModel):
    interview_date: datetime
    round: str = "Phone Screen"
    interviewer_name: Optional[str] = None
    interviewer_role: Optional[str] = None
    interviewer_linkedin: Optional[str] = None
    notes: Optional[str] = None


class DebriefCreate(BaseModel):
    rating: int = Field(..., ge=1, le=10)
    questions_asked: Optional[str] = None
    went_well: Optional[str] = None
    to_improve: Optional[str] = None
    next_steps: Optional[str] = None


class FollowupAction(BaseModel):
    notes: Optional[str] = None


# --- Existing endpoints ---

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
        status=data.get("status") or "Tracking",
        fit_score=data.get("fit_score"),
        ats_score=data.get("ats_score"),
        resume_version=data.get("resume_version"),
        apply_type=data.get("apply_type"),
        referral_contact=data.get("referral_contact"),
        notes=data.get("notes"),
        applied_date=data.get("applied_date") or datetime.now(timezone.utc).date(),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return JobOut.model_validate(job)


# --- FIXED-PATH ENDPOINTS (MUST be before /{job_id}) ---

@router.get("/pipeline")
async def get_pipeline(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get comprehensive pipeline view with aggregations and actionable lists."""
    today = datetime.now(timezone.utc).date()

    all_jobs = (
        await db.execute(
            select(Job)
            .where(Job.user_id == current_user.id, Job.is_deleted.is_(False))
            .order_by(Job.updated_at.desc())
        )
    ).scalars().all()

    pipeline = {}
    for job in all_jobs:
        pipeline[job.status] = pipeline.get(job.status, 0) + 1

    inactive_statuses = {"Closed"}
    active_count = sum(count for status, count in pipeline.items() if status not in inactive_statuses)

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

    stale = []
    stale_threshold = today - timedelta(days=14)
    for job in all_jobs:
        if job.status in ("Applied", "Tracking") and job.updated_at and job.updated_at.date() <= stale_threshold:
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


@router.get("/stale")
async def get_stale_jobs(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Jobs in 'Applied' or 'Tracking' status where updated_at is 14+ days ago."""
    fourteen_days_ago = datetime.now(timezone.utc) - timedelta(days=14)
    query = select(Job).where(
        Job.user_id == current_user.id,
        Job.status.in_(["Applied", "Tracking"]),
        Job.updated_at < fourteen_days_ago,
        Job.is_deleted.is_(False),
    ).order_by(Job.updated_at.asc())
    result = await db.execute(query)
    jobs = result.scalars().all()

    stale_list = []
    for job in jobs:
        days = (datetime.now(timezone.utc) - job.updated_at).days
        stale_list.append({
            "id": str(job.id),
            "company": job.company_name,
            "role": job.role_title,
            "status": job.status,
            "applied_date": str(job.applied_date) if job.applied_date else None,
            "days_since_update": days,
            "suggested_action": "Follow up" if days < 21 else "Final follow-up or mark as Closed",
        })
    return {"stale_jobs": stale_list, "count": len(stale_list)}


@router.get("/followups")
async def get_followups(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Tiered follow-up system: 7-day, 14-day, 21-day."""
    now = datetime.now(timezone.utc)
    jobs = (
        await db.execute(
            select(Job).where(
                Job.user_id == current_user.id,
                Job.status.in_(["Applied", "Tracking"]),
                Job.is_deleted.is_(False),
            )
        )
    ).scalars().all()

    day_7 = []
    day_14 = []
    day_21 = []

    for job in jobs:
        if not job.applied_date:
            continue
        days_since_applied = (now.date() - job.applied_date).days

        # Check if followup is actually needed
        last_fu = job.last_followup_date
        needs_followup = last_fu is None or (now.date() - last_fu).days >= 7

        if not needs_followup:
            continue

        entry = {
            "id": str(job.id),
            "company": job.company_name,
            "role": job.role_title,
            "days": days_since_applied,
        }

        if 7 <= days_since_applied < 14:
            entry["action"] = "Gentle follow-up email"
            day_7.append(entry)
        elif 14 <= days_since_applied < 21:
            entry["action"] = "Second follow-up with value add"
            day_14.append(entry)
        elif days_since_applied >= 21:
            entry["action"] = "Final follow-up or mark as Closed"
            day_21.append(entry)

    return {
        "day_7": day_7,
        "day_14": day_14,
        "day_21": day_21,
        "total_needing_action": len(day_7) + len(day_14) + len(day_21),
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
        job = Job(
            user_id=current_user.id,
            company_name=company_name,
            role_title=role_title,
            jd_text=payload.jd_text,
            jd_url=payload.jd_url,
            status="Tracking",
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

    await log_activity(db, current_user.id, "job_analyzed", f"Analyzed JD: {company_name} - {role_title}", related_job_id=job.id)
    await db.commit()

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


# --- PARAMETRIC ENDPOINTS (MUST be after fixed-path endpoints) ---

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

    old_status = job.status
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)

    # Default closed_reason when status changes to 'Closed'
    if update_data.get("status") == "Closed" and job.closed_reason is None:
        job.closed_reason = "No Response"

    await db.commit()
    await db.refresh(job)

    if payload.status and payload.status != old_status:
        await log_activity(
            db, current_user.id, "job_status_changed",
            f"Status changed: {job.company_name} - {job.role_title} ({old_status} → {payload.status})",
            related_job_id=job.id,
        )
        await db.commit()

    return JobOut.model_validate(job)


@router.delete("/{job_id}")
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)) -> dict:
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    job.is_deleted = True
    await db.commit()
    return {"status": "deleted"}


@router.patch("/{job_id}/followup")
async def log_followup(
    job_id: str,
    payload: FollowupAction,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Log that a follow-up was sent."""
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")

    job.last_followup_date = date.today()
    job.followup_count = (job.followup_count or 0) + 1
    if payload.notes:
        existing = job.notes if job.notes is not None else []
        existing.append({
            "text": f"[Follow-up {date.today()}] {payload.notes}",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        job.notes = existing
        flag_modified(job, "notes")

    await db.commit()
    await db.refresh(job)

    await log_activity(
        db, current_user.id, "contact_followup",
        f"Followed up on {job.company_name} - {job.role_title}",
        related_job_id=job.id,
    )
    await db.commit()

    return {
        "id": str(job.id),
        "company": job.company_name,
        "role": job.role_title,
        "last_followup_date": str(job.last_followup_date),
        "followup_count": job.followup_count,
    }


@router.post("/{job_id}/notes")
async def add_note(
    job_id: str,
    payload: AddNoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Add a note to a job's notes JSONB array."""
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = job.notes if job.notes is not None else []
    existing.append({
        "text": payload.text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    job.notes = existing
    flag_modified(job, "notes")
    await db.commit()
    await db.refresh(job)
    return {"notes": job.notes}


@router.post("/{job_id}/interview")
async def schedule_interview(
    job_id: str,
    payload: InterviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Schedule an interview for a job."""
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")

    interview = Interview(
        user_id=current_user.id,
        job_id=job.id,
        interview_date=payload.interview_date,
        round=payload.round,
        interviewer_name=payload.interviewer_name,
        interviewer_role=payload.interviewer_role,
        interviewer_linkedin=payload.interviewer_linkedin,
        notes=payload.notes,
        status="Scheduled",
    )
    db.add(interview)

    # Update job status if currently Applied or Tracking
    if job.status in ("Applied", "Tracking"):
        job.status = "Interview"

    await db.commit()
    await db.refresh(interview)

    date_str = payload.interview_date.strftime("%Y-%m-%d %H:%M")
    await log_activity(
        db, current_user.id, "interview_scheduled",
        f"Interview scheduled: {job.company_name} - {job.role_title}, {payload.round} on {date_str}",
        related_job_id=job.id,
    )
    await db.commit()

    return {
        "id": str(interview.id),
        "job_id": str(job.id),
        "company": job.company_name,
        "role": job.role_title,
        "interview_date": interview.interview_date.isoformat(),
        "round": interview.round,
        "interviewer_name": interview.interviewer_name,
        "interviewer_role": interview.interviewer_role,
        "status": interview.status,
    }


@router.post("/{job_id}/debrief")
async def log_debrief(
    job_id: str,
    payload: DebriefCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Log debrief after an interview."""
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")

    # Find most recent interview for this job
    result = await db.execute(
        select(Interview).where(
            Interview.job_id == job.id,
            Interview.status.in_(["Scheduled", "Completed"]),
        ).order_by(Interview.interview_date.desc())
    )
    interview = result.scalars().first()
    if interview is None:
        raise HTTPException(status_code=404, detail="No interview found for this job")

    interview.rating = payload.rating
    interview.questions_asked = payload.questions_asked
    interview.went_well = payload.went_well
    interview.to_improve = payload.to_improve
    interview.next_steps = payload.next_steps
    interview.status = "Completed"

    # Update job status
    job.status = "Interview"

    await db.commit()
    await db.refresh(interview)

    await log_activity(
        db, current_user.id, "interview_completed",
        f"Interview debriefed: {job.company_name} - {job.role_title}, rated {payload.rating}/10",
        related_job_id=job.id,
    )
    await db.commit()

    return {
        "id": str(interview.id),
        "job_id": str(job.id),
        "company": job.company_name,
        "role": job.role_title,
        "rating": interview.rating,
        "status": interview.status,
        "questions_asked": interview.questions_asked,
        "went_well": interview.went_well,
        "to_improve": interview.to_improve,
        "next_steps": interview.next_steps,
    }


@router.get("/{job_id}/prep")
async def get_interview_prep(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate AI interview prep. Cached for 48 hours."""
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check for cached prep on any interview for this job
    result = await db.execute(
        select(Interview).where(Interview.job_id == job.id).order_by(Interview.interview_date.desc())
    )
    interview = result.scalars().first()

    # Check cache
    if interview and interview.prep_content and interview.prep_generated_at:
        age = datetime.now(timezone.utc) - interview.prep_generated_at
        if age < timedelta(hours=48):
            return {"prep": interview.prep_content, "cached": True, "generated_at": interview.prep_generated_at.isoformat()}

    # Gather data for prep
    prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = prof_res.scalar_one_or_none()

    profile_data = ""
    if profile:
        profile_data = f"Name: {profile.full_name}\nPositioning: {profile.positioning_statement}\nSkills: {', '.join(profile.core_skills or [])}\nAchievements: {profile.achievements}"

    # Get company data
    company_result = await db.execute(
        select(Company).where(
            Company.user_id == current_user.id,
            func.lower(Company.name) == func.lower(job.company_name),
        )
    )
    company = company_result.scalars().first()
    company_context = company.deep_dive_content if company and company.deep_dive_content else f"Company: {job.company_name}"

    interviewer_info = ""
    if interview:
        if interview.interviewer_name:
            interviewer_info = f"{interview.interviewer_name}, {interview.interviewer_role or 'Unknown role'}"

    round_info = interview.round if interview else "Unknown"

    prompt = f"""You are a career coach preparing a candidate for an interview.

CANDIDATE:
{profile_data}

COMPANY: {job.company_name}
ROLE: {job.role_title}
ROUND: {round_info}
INTERVIEWER: {interviewer_info if interviewer_info else 'Not specified'}

COMPANY CONTEXT:
{company_context[:3000]}

Generate:
1. Company overview (3-4 sentences, focused on what matters for THIS role)
2. Recent developments that could come up
3. 5 predicted questions with suggested STAR-format answers using the candidate's experience
4. 3 thoughtful questions the candidate should ask
5. A 90-day plan skeleton for this specific role

Keep total under 1500 words. Be specific, not generic."""

    try:
        prep_content = await call_claude(prompt, max_tokens=3000)
    except Exception:
        return {
            "error": "AI service temporarily unavailable",
            "fallback": f"Company: {job.company_name}. Review your notes and the JD analysis.",
        }

    if prep_content is None:
        return {
            "error": "AI service temporarily unavailable",
            "fallback": f"Company: {job.company_name}. Review your notes and the JD analysis.",
        }

    # Cache the result
    if interview:
        interview.prep_content = prep_content
        interview.prep_generated_at = datetime.now(timezone.utc)
        await db.commit()

    return {"prep": prep_content, "cached": False, "generated_at": datetime.now(timezone.utc).isoformat()}
