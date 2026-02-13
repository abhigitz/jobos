from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.activity_log import ActivityLog
from app.models.company import Company
from app.models.contact import Contact
from app.models.content import ContentCalendar
from app.models.daily_log import DailyLog
from app.models.interview import Interview
from app.models.job import Job
from app.models.weekly_metrics import WeeklyMetrics
from app.schemas.analytics import DailyLogIn, DailyLogOut, DashboardOut, WeeklyReviewOut
from app.services.ai_service import generate_weekly_review


router = APIRouter()


def _compute_streak(logs_by_date: dict[date, object], today: date) -> int:
    """Compute streak, excluding Sundays from breaking it."""
    streak = 0
    day_cursor = today
    while True:
        log = logs_by_date.get(day_cursor)
        is_sunday = day_cursor.weekday() == 6  # 6 = Sunday

        if log and log.jobs_applied > 0:
            streak += 1
            day_cursor -= timedelta(days=1)
        elif is_sunday:
            # Sundays don't break streak, just skip
            day_cursor -= timedelta(days=1)
        else:
            break
    return streak


# --- Existing endpoints ---

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


# --- New endpoints ---

@router.get("/funnel")
async def get_funnel(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Funnel aggregation by status."""
    cutoff = date.today() - timedelta(days=days)

    status_rows = (
        await db.execute(
            select(Job.status, func.count()).where(
                Job.user_id == current_user.id,
                Job.is_deleted.is_(False),
                Job.created_at >= cutoff,
            ).group_by(Job.status)
        )
    ).all()
    funnel = {s: c for s, c in status_rows}

    total = sum(funnel.values())
    result = {"funnel": funnel, "total": total, "days": days}

    if total < 5:
        result["note"] = "Apply to more roles for meaningful conversion data."

    return result


@router.get("/sources")
async def get_sources(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Group by source_portal, count total and responses."""
    rows = (
        await db.execute(
            select(Job.source_portal, func.count()).where(
                Job.user_id == current_user.id,
                Job.is_deleted.is_(False),
            ).group_by(Job.source_portal)
        )
    ).all()

    if not rows:
        return {"sources": [], "note": "Log your application sources to see which portals work best."}

    response_statuses = {"Applied", "Interview", "Offer"}
    sources = []
    for portal, total in rows:
        response_count = (
            await db.execute(
                select(func.count()).where(
                    Job.user_id == current_user.id,
                    Job.source_portal == portal,
                    Job.status.in_(response_statuses),
                    Job.is_deleted.is_(False),
                )
            )
        ).scalar_one()
        sources.append({
            "source": portal or "Unknown",
            "total": total,
            "responses": response_count,
            "response_rate": round(response_count / total * 100, 1) if total > 0 else 0,
        })

    sources.sort(key=lambda x: x["response_rate"], reverse=True)
    return {"sources": sources}


@router.get("/weekly-trend")
async def get_weekly_trend(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns last 4 weeks of aggregated daily_log data."""
    today = date.today()
    weeks = []

    for w in range(4):
        week_end = today - timedelta(days=today.weekday()) - timedelta(weeks=w)
        week_start = week_end - timedelta(days=6)

        logs = (
            await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == current_user.id,
                    DailyLog.log_date >= week_start,
                    DailyLog.log_date <= week_end,
                )
            )
        ).scalars().all()

        energy_logs = [l.energy_level for l in logs if l.energy_level]
        avg_energy = round(sum(energy_logs) / len(energy_logs), 1) if energy_logs else None

        weeks.append({
            "week_start": week_start.isoformat(),
            "jobs_applied": sum(l.jobs_applied for l in logs),
            "connections_sent": sum(l.connections_sent for l in logs),
            "avg_energy": avg_energy,
        })

    weeks.reverse()
    return {"weeks": weeks}


@router.get("/energy")
async def get_energy_correlation(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Correlate energy_level with activity metrics."""
    logs = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.energy_level.is_not(None),
            ).order_by(DailyLog.log_date.desc())
        )
    ).scalars().all()

    if len(logs) < 7:
        return {"note": "Log energy levels for 7+ days to see correlations.", "data": None}

    # Group by energy level
    by_energy: dict[int, list] = {}
    for log in logs:
        level = log.energy_level
        if level not in by_energy:
            by_energy[level] = []
        by_energy[level].append({
            "jobs_applied": log.jobs_applied,
            "connections_sent": log.connections_sent,
        })

    correlation = {}
    for level, entries in sorted(by_energy.items()):
        correlation[level] = {
            "days": len(entries),
            "avg_jobs_applied": round(sum(e["jobs_applied"] for e in entries) / len(entries), 1),
            "avg_connections_sent": round(sum(e["connections_sent"] for e in entries) / len(entries), 1),
        }

    return {"data": correlation, "total_days": len(logs)}


@router.get("/resume-performance")
async def get_resume_performance(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Group jobs by resume_version."""
    rows = (
        await db.execute(
            select(Job.resume_version, func.count()).where(
                Job.user_id == current_user.id,
                Job.is_deleted.is_(False),
                Job.resume_version.is_not(None),
            ).group_by(Job.resume_version)
        )
    ).all()

    response_statuses = {"Applied", "Interview", "Offer"}
    versions = []
    for version, total in rows:
        response_count = (
            await db.execute(
                select(func.count()).where(
                    Job.user_id == current_user.id,
                    Job.resume_version == version,
                    Job.status.in_(response_statuses),
                    Job.is_deleted.is_(False),
                )
            )
        ).scalar_one()
        versions.append({
            "resume_version": version,
            "total_sent": total,
            "responses": response_count,
            "response_rate": round(response_count / total * 100, 1) if total > 0 else 0,
        })

    return {"versions": versions}


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    """Enhanced dashboard — home page data source."""
    today = date.today()

    # --- TODAY's log ---
    today_log_result = await db.execute(
        select(DailyLog).where(DailyLog.user_id == current_user.id, DailyLog.log_date == today)
    )
    today_log = today_log_result.scalar_one_or_none()
    today_data = None
    if today_log:
        today_data = {
            "jobs_applied": today_log.jobs_applied,
            "connections_sent": today_log.connections_sent,
            "comments_made": today_log.comments_made,
            "energy_level": today_log.energy_level,
        }

    # --- Pipeline snapshot ---
    status_rows = (
        await db.execute(
            select(Job.status, func.count()).where(
                Job.user_id == current_user.id, Job.is_deleted.is_(False)
            ).group_by(Job.status)
        )
    ).all()
    pipeline_breakdown = {s: c for s, c in status_rows}

    total_applied = sum(c for s, c in status_rows if s not in ("Analyzed",))
    total_interviews = sum(c for s, c in status_rows if s in ("Interview", "Offer"))

    # --- This week ---
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

    # --- Alerts ---
    # Stale count
    fourteen_days_ago = today - timedelta(days=14)
    stale_count = (
        await db.execute(
            select(func.count()).where(
                Job.user_id == current_user.id,
                Job.status == "Applied",
                Job.is_deleted.is_(False),
            )
        )
    ).scalar_one()  # Simplified — will filter in Python if needed

    # Followup count
    follow_ups_due = (
        await db.execute(
            select(func.count()).where(
                Contact.user_id == current_user.id,
                Contact.is_deleted.is_(False),
                Contact.follow_up_date.is_not(None),
                Contact.follow_up_date <= today,
            )
        )
    ).scalar_one()

    # Upcoming interviews count
    upcoming_interviews_count = (
        await db.execute(
            select(func.count()).where(
                Interview.user_id == current_user.id,
                Interview.status == "Scheduled",
                Interview.interview_date >= today,
            )
        )
    ).scalar_one()

    # Content status today
    content_today_result = await db.execute(
        select(ContentCalendar).where(
            ContentCalendar.user_id == current_user.id,
            ContentCalendar.scheduled_date == today,
        )
    )
    content_today = content_today_result.scalar_one_or_none()
    content_status = None
    if content_today:
        content_status = {"topic": content_today.topic, "status": content_today.status}

    # --- Recent activity ---
    recent_activity_rows = (
        await db.execute(
            select(ActivityLog).where(
                ActivityLog.user_id == current_user.id
            ).order_by(ActivityLog.created_at.desc()).limit(5)
        )
    ).scalars().all()
    recent_activity = [
        {
            "action_type": a.action_type,
            "description": a.description,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in recent_activity_rows
    ]

    # --- Streak (Sunday-exempt) ---
    # Fetch last 60 days of logs for streak calculation
    cutoff = today - timedelta(days=60)
    all_logs = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.log_date >= cutoff,
            )
        )
    ).scalars().all()
    logs_by_date = {log.log_date: log for log in all_logs}
    streak_days = _compute_streak(logs_by_date, today)

    # --- Top companies ---
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

    # --- Next interview ---
    next_interview_result = await db.execute(
        select(Interview).where(
            Interview.user_id == current_user.id,
            Interview.status == "Scheduled",
            Interview.interview_date >= today,
        ).order_by(Interview.interview_date.asc()).limit(1)
    )
    next_iv = next_interview_result.scalar_one_or_none()
    next_interview = None
    if next_iv:
        job = await db.get(Job, next_iv.job_id)
        next_interview = {
            "company": job.company_name if job else "Unknown",
            "role": job.role_title if job else "Unknown",
            "date": next_iv.interview_date.isoformat(),
            "round": next_iv.round,
        }

    return {
        "today": today_data,
        "total_applied": total_applied,
        "total_interviews": total_interviews,
        "pipeline_breakdown": pipeline_breakdown,
        "this_week": this_week,
        "streak_days": streak_days,
        "top_companies": top_companies,
        "follow_ups_due_today": follow_ups_due,
        "next_interview": next_interview,
        "alerts": {
            "stale_applications": stale_count,
            "followups_due": follow_ups_due,
            "upcoming_interviews": upcoming_interviews_count,
            "content_today": content_status,
        },
        "recent_activity": recent_activity,
    }
