from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.interview import Interview
from app.models.job import Job


router = APIRouter()


@router.get("/upcoming")
async def get_upcoming_interviews(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns interviews in the next 7 days and past this week."""
    now = datetime.now(timezone.utc)
    seven_days_later = now + timedelta(days=7)
    week_start = now - timedelta(days=now.weekday())

    # Upcoming interviews (next 7 days)
    upcoming_result = await db.execute(
        select(Interview).where(
            Interview.user_id == current_user.id,
            Interview.interview_date >= now,
            Interview.interview_date <= seven_days_later,
            Interview.status == "Scheduled",
        ).order_by(Interview.interview_date.asc())
    )
    upcoming_interviews = upcoming_result.scalars().all()

    upcoming = []
    for iv in upcoming_interviews:
        job = await db.get(Job, iv.job_id)
        days_until = (iv.interview_date - now).days
        upcoming.append({
            "id": str(iv.id),
            "job_id": str(iv.job_id),
            "company": job.company_name if job else "Unknown",
            "role": job.role_title if job else "Unknown",
            "interview_date": iv.interview_date.isoformat(),
            "round": iv.round,
            "interviewer_name": iv.interviewer_name,
            "days_until": days_until,
            "has_prep": iv.prep_content is not None,
        })

    # Past interviews this week
    past_result = await db.execute(
        select(Interview).where(
            Interview.user_id == current_user.id,
            Interview.interview_date >= week_start,
            Interview.interview_date < now,
        ).order_by(Interview.interview_date.desc())
    )
    past_interviews = past_result.scalars().all()

    past_this_week = []
    for iv in past_interviews:
        job = await db.get(Job, iv.job_id)
        past_this_week.append({
            "id": str(iv.id),
            "company": job.company_name if job else "Unknown",
            "role": job.role_title if job else "Unknown",
            "interview_date": iv.interview_date.isoformat(),
            "rating": iv.rating,
            "has_debrief": iv.questions_asked is not None or iv.went_well is not None,
        })

    # Common questions from past interviews
    all_completed = await db.execute(
        select(Interview).where(
            Interview.user_id == current_user.id,
            Interview.status == "Completed",
            Interview.questions_asked.is_not(None),
        )
    )
    all_completed_interviews = all_completed.scalars().all()

    word_counter: Counter[str] = Counter()
    for iv in all_completed_interviews:
        if iv.questions_asked:
            words = iv.questions_asked.lower().split()
            # Extract meaningful phrases (3+ chars, skip common words)
            skip = {"the", "and", "for", "was", "how", "what", "why", "you", "your", "with", "that", "this", "have", "from", "they", "about"}
            meaningful = [w.strip(".,?!;:") for w in words if len(w) > 3 and w not in skip]
            word_counter.update(meaningful)

    common_questions = [word for word, _ in word_counter.most_common(5)]

    return {
        "upcoming": upcoming,
        "past_this_week": past_this_week,
        "common_questions": common_questions,
    }


@router.get("/{interview_id}")
async def get_interview(
    interview_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return single interview with full details."""
    interview = await db.get(Interview, interview_id)
    if interview is None or interview.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Interview not found")

    job = await db.get(Job, interview.job_id)

    return {
        "id": str(interview.id),
        "job_id": str(interview.job_id),
        "company": job.company_name if job else "Unknown",
        "role": job.role_title if job else "Unknown",
        "interview_date": interview.interview_date.isoformat(),
        "round": interview.round,
        "interviewer_name": interview.interviewer_name,
        "interviewer_role": interview.interviewer_role,
        "interviewer_linkedin": interview.interviewer_linkedin,
        "status": interview.status,
        "notes": interview.notes,
        "rating": interview.rating,
        "questions_asked": interview.questions_asked,
        "went_well": interview.went_well,
        "to_improve": interview.to_improve,
        "next_steps": interview.next_steps,
        "prep_content": interview.prep_content,
        "prep_generated_at": interview.prep_generated_at.isoformat() if interview.prep_generated_at else None,
        "created_at": interview.created_at.isoformat(),
    }
