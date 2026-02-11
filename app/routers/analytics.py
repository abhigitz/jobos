from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company
from app.models.contact import Contact
from app.models.daily_log import DailyLog
from app.models.job import Job
from app.models.weekly_metrics import WeeklyMetrics
from app.schemas.analytics import DailyLogIn, DailyLogOut, DashboardOut, WeeklyReviewOut
from app.services.ai_service import generate_weekly_review


router = APIRouter()


@router.get("/daily-log", response_model=list[DailyLogOut])
async def get_daily_logs(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[DailyLogOut]:
    query = select(DailyLog).where(DailyLog.user_id == current_user.id)
    if start_date:
        query = query.where(DailyLog.log_date >= start_date)
    if end_date:
        query = query.where(DailyLog.log_date <= end_date)
    rows = (await db.execute(query.order_by(DailyLog.log_date.desc()))).scalars().all()
    return [DailyLogOut.model_validate(r) for r in rows]


@router.post("/daily-log", response_model=DailyLogOut)
async def upsert_daily_log(
    payload: DailyLogIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> DailyLogOut:
    result = await db.execute(
        select(DailyLog).where(DailyLog.user_id == current_user.id, DailyLog.log_date == payload.log_date)
    )
    log = result.scalar_one_or_none()
    if log is None:
        log = DailyLog(user_id=current_user.id, **payload.model_dump())
        db.add(log)
    else:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(log, field, value)
    await db.commit()
    await db.refresh(log)
    return DailyLogOut.model_validate(log)


@router.get("/weekly-review", response_model=list[WeeklyReviewOut])
async def get_weekly_reviews(
    week_number: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[WeeklyReviewOut]:
    query = select(WeeklyMetrics).where(WeeklyMetrics.user_id == current_user.id)
    if week_number is not None:
        query = query.where(WeeklyMetrics.week_number == week_number)
    rows = (await db.execute(query.order_by(WeeklyMetrics.week_start.desc()))).scalars().all()
    return [WeeklyReviewOut.model_validate(r) for r in rows]


@router.post("/weekly-review/generate", response_model=WeeklyReviewOut)
async def generate_weekly_review_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> WeeklyReviewOut:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    logs = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.log_date >= week_start,
                DailyLog.log_date <= week_end,
            )
        )
    ).scalars().all()

    data = {
        "logs": [
            {
                "log_date": l.log_date,
                "jobs_applied": l.jobs_applied,
                "connections_sent": l.connections_sent,
                "comments_made": l.comments_made,
            }
            for l in logs
        ]
    }

    analysis = await generate_weekly_review(data) or ""

    metrics = WeeklyMetrics(
        user_id=current_user.id,
        week_number=week_start.isocalendar().week,
        week_start=week_start,
        week_end=week_end,
        total_applied=sum(l.jobs_applied for l in logs),
        total_connections=sum(l.connections_sent for l in logs),
        total_calls=sum(l.networking_calls for l in logs),
        total_referrals=sum(l.referrals_asked for l in logs),
        posts_published=sum(1 for l in logs if l.post_published),
        interviews_scheduled=0,
        response_rate=None,
        ai_analysis=analysis,
    )
    db.add(metrics)
    await db.commit()
    await db.refresh(metrics)
    return WeeklyReviewOut.model_validate(metrics)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)) -> DashboardOut:
    total_applied = (
        await db.execute(
            select(func.count()).where(
                Job.user_id == current_user.id,
                Job.status.in_(["Applied", "Screening", "Interview_Scheduled", "Interview_Done", "Offer"]),
                Job.is_deleted.is_(False),
            )
        )
    ).scalar_one()

    total_interviews = (
        await db.execute(
            select(func.count()).where(
                Job.user_id == current_user.id,
                Job.status.in_(["Interview_Scheduled", "Interview_Done", "Offer"]),
                Job.is_deleted.is_(False),
            )
        )
    ).scalar_one()

    status_rows = (
        await db.execute(
            select(Job.status, func.count()).where(Job.user_id == current_user.id, Job.is_deleted.is_(False)).group_by(Job.status)
        )
    ).all()
    pipeline_breakdown = {s: c for s, c in status_rows}

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    logs_week = (
        await db.execute(
            select(DailyLog).where(DailyLog.user_id == current_user.id, DailyLog.log_date >= week_start)
        )
    ).scalars().all()
    this_week = {
        "applied": sum(l.jobs_applied for l in logs_week),
        "connections": sum(l.connections_sent for l in logs_week),
        "comments": sum(l.comments_made for l in logs_week),
    }

    # streak_days: consecutive days with any activity
    streak = 0
    day_cursor = today
    while True:
        log_row = (
            await db.execute(
                select(DailyLog).where(DailyLog.user_id == current_user.id, DailyLog.log_date == day_cursor)
            )
        ).scalar_one_or_none()
        if log_row and (
            log_row.jobs_applied
            or log_row.connections_sent
            or log_row.comments_made
            or log_row.networking_calls
            or log_row.referrals_asked
        ):
            streak += 1
            day_cursor -= timedelta(days=1)
        else:
            break

    follow_ups_due_today = (
        await db.execute(
            select(func.count()).where(
                Contact.user_id == current_user.id,
                Contact.is_deleted.is_(False),
                Contact.follow_up_date <= today,
            )
        )
    ).scalar_one()

    next_interview_row = (
        await db.execute(
            select(Job)
            .where(
                Job.user_id == current_user.id,
                Job.interview_date.is_not(None),
                Job.is_deleted.is_(False),
            )
            .order_by(Job.interview_date.asc())
        )
    ).scalars().first()
    next_interview = None
    if next_interview_row:
        next_interview = {
            "company": next_interview_row.company_name,
            "date": next_interview_row.interview_date,
            "role": next_interview_row.role_title,
        }

    top_company_rows = (
        await db.execute(
            select(Company.name, func.count())
            .join(Job, Job.company_name == Company.name)
            .where(Job.user_id == current_user.id, Job.is_deleted.is_(False))
            .group_by(Company.name)
            .order_by(func.count().desc())
            .limit(3)
        )
    ).all()
    top_companies = [name for name, _ in top_company_rows]

    return DashboardOut(
        total_applied=total_applied,
        total_interviews=total_interviews,
        pipeline_breakdown=pipeline_breakdown,
        this_week=this_week,
        streak_days=streak,
        top_companies=top_companies,
        follow_ups_due_today=follow_ups_due_today,
        next_interview=next_interview,
    )
