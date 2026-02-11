from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company
from app.models.contact import Contact
from app.models.content import ContentCalendar
from app.models.daily_log import DailyLog
from app.models.jd_keyword import JDKeyword
from app.models.job import Job
from app.models.profile import ProfileDNA
from app.models.weekly_metrics import WeeklyMetrics
from app.services.ai_service import (
    generate_morning_briefing,
    generate_midday_check,
    generate_weekly_review,
)

router = APIRouter()


@router.get("/morning")
async def get_morning_briefing(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate AI-powered morning briefing with actionable priorities."""
    today = date.today()
    
    # Gather data for briefing
    # 1. Active pipeline jobs
    jobs = (
        await db.execute(
            select(Job).where(
                Job.user_id == current_user.id,
                Job.is_deleted.is_(False),
                Job.status.in_(["Applied", "Screening", "Interview Scheduled"]),
            )
        )
    ).scalars().all()
    
    # 2. Follow-ups due today or overdue
    contacts_due = (
        await db.execute(
            select(Contact).where(
                Contact.user_id == current_user.id,
                Contact.is_deleted.is_(False),
                Contact.follow_up_date.is_not(None),
                Contact.follow_up_date <= today,
                Contact.referral_status != "Outcome",
            )
        )
    ).scalars().all()
    
    # 3. Stale applications (14+ days)
    stale_threshold = today - timedelta(days=14)
    stale_jobs = [
        j for j in (
            await db.execute(
                select(Job).where(
                    Job.user_id == current_user.id,
                    Job.is_deleted.is_(False),
                    Job.status == "Applied",
                )
            )
        ).scalars().all()
        if j.updated_at.date() <= stale_threshold
    ]
    
    # 4. Yesterday's activity
    yesterday = today - timedelta(days=1)
    yesterday_log = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.log_date == yesterday,
            )
        )
    ).scalar_one_or_none()
    
    # 5. Today's content topic
    content_today = (
        await db.execute(
            select(ContentCalendar).where(
                ContentCalendar.user_id == current_user.id,
                ContentCalendar.scheduled_date == today,
            )
        )
    ).scalar_one_or_none()
    
    # 6. Next company for deep-dive (from company rotation or oldest researched)
    next_company = (
        await db.execute(
            select(Company)
            .where(Company.user_id == current_user.id)
            .order_by(Company.last_researched.asc().nulls_first())
            .limit(1)
        )
    ).scalar_one_or_none()
    
    # 7. Get profile for context
    profile_res = await db.execute(
        select(ProfileDNA).where(ProfileDNA.user_id == current_user.id)
    )
    profile = profile_res.scalar_one_or_none()
    
    # 8. Calculate streak (consecutive days with activity)
    streak_days = 0
    check_date = today - timedelta(days=1)  # Start from yesterday
    while True:
        log = (
            await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == current_user.id,
                    DailyLog.log_date == check_date,
                )
            )
        ).scalar_one_or_none()
        
        if log and (log.jobs_applied > 0 or log.connections_sent > 0 or log.comments_made > 0):
            streak_days += 1
            check_date -= timedelta(days=1)
        else:
            break
    
    # Build data dict for AI
    data = {
        "today": today.isoformat(),
        "profile": {
            "name": profile.full_name if profile else "User",
            "target_roles": profile.target_roles if profile else [],
            "positioning": profile.positioning_statement if profile else "",
        },
        "active_pipeline": [
            {
                "company": j.company_name,
                "role": j.role_title,
                "status": j.status,
                "days_since_update": (today - j.updated_at.date()).days,
            }
            for j in jobs
        ],
        "followups_due": [
            {
                "name": c.name,
                "company": c.company,
                "connection_type": c.connection_type,
                "days_overdue": (today - c.follow_up_date).days if c.follow_up_date else 0,
            }
            for c in contacts_due
        ],
        "stale_applications": [
            {
                "company": j.company_name,
                "role": j.role_title,
                "days_since_update": (today - j.updated_at.date()).days,
            }
            for j in stale_jobs
        ],
        "yesterday_activity": {
            "jobs_applied": yesterday_log.jobs_applied if yesterday_log else 0,
            "connections_sent": yesterday_log.connections_sent if yesterday_log else 0,
            "comments_made": yesterday_log.comments_made if yesterday_log else 0,
        } if yesterday_log else None,
        "today_content_topic": {
            "topic": content_today.topic,
            "category": content_today.category,
        } if content_today else None,
        "deep_dive_company": next_company.name if next_company else None,
        "streak_days": streak_days,
    }
    
    # Generate briefing with AI
    briefing_text = await generate_morning_briefing(data)
    
    return {
        "briefing": briefing_text or "Unable to generate briefing at this time.",
        "generated_at": today.isoformat(),
        "stats": {
            "active_applications": len(jobs),
            "followups_due": len(contacts_due),
            "stale_count": len(stale_jobs),
            "streak_days": streak_days,
        },
    }


@router.get("/midday")
async def get_midday_check(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate mid-day accountability check."""
    today = date.today()
    
    # Get today's log if it exists
    today_log = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.log_date == today,
            )
        )
    ).scalar_one_or_none()
    
    # Get last 3 days for context
    last_3_days = []
    for i in range(1, 4):
        check_date = today - timedelta(days=i)
        log = (
            await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == current_user.id,
                    DailyLog.log_date == check_date,
                )
            )
        ).scalar_one_or_none()
        if log:
            last_3_days.append({
                "date": check_date.isoformat(),
                "jobs_applied": log.jobs_applied,
                "connections_sent": log.connections_sent,
            })
    
    data = {
        "today": today.isoformat(),
        "today_log": {
            "jobs_applied": today_log.jobs_applied if today_log else 0,
            "connections_sent": today_log.connections_sent if today_log else 0,
            "comments_made": today_log.comments_made if today_log else 0,
        } if today_log else None,
        "last_3_days": last_3_days,
        "morning_targets": {
            "applications": 3,  # Default targets
            "connections": 4,
            "comments": 3,
        },
    }
    
    message = await generate_midday_check(data)
    
    return {
        "message": message or "Keep going! Make progress on your applications today.",
        "generated_at": today.isoformat(),
    }


@router.post("/evening")
async def process_evening_checkin(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Process evening check-in: save log and generate tomorrow's priorities."""
    today = date.today()
    
    # Extract check-in data
    log_data = {
        "log_date": today,
        "jobs_applied": payload.get("jobs_applied", 0),
        "connections_sent": payload.get("connections_sent", 0),
        "comments_made": payload.get("comments_made", 0),
        "post_published": payload.get("post_published", False),
        "networking_calls": payload.get("networking_calls", 0),
        "referrals_asked": payload.get("referrals_asked", 0),
        "naukri_updated": payload.get("naukri_updated", False),
        "deep_dive_company": payload.get("deep_dive_company"),
        "energy_level": payload.get("energy_level"),
        "mood": payload.get("mood"),
    }
    
    # Upsert daily log
    existing = await db.execute(
        select(DailyLog).where(
            DailyLog.user_id == current_user.id,
            DailyLog.log_date == today,
        )
    )
    log = existing.scalar_one_or_none()
    
    if log:
        for key, value in log_data.items():
            if key != "log_date":
                setattr(log, key, value)
    else:
        log = DailyLog(user_id=current_user.id, **log_data)
        db.add(log)
    
    await db.commit()
    
    # Get last 7 days for trend
    last_7_days = []
    for i in range(1, 8):
        check_date = today - timedelta(days=i)
        past_log = (
            await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == current_user.id,
                    DailyLog.log_date == check_date,
                )
            )
        ).scalar_one_or_none()
        if past_log:
            last_7_days.append({
                "date": check_date.isoformat(),
                "jobs_applied": past_log.jobs_applied,
                "connections_sent": past_log.connections_sent,
                "energy_level": past_log.energy_level,
            })
    
    # Get active pipeline count
    active_count = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.log_date == today,
            )
        )
    ).scalar_one_or_none()
    
    pipeline_counts = {}
    jobs = (
        await db.execute(
            select(Job).where(
                Job.user_id == current_user.id,
                Job.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    for j in jobs:
        pipeline_counts[j.status] = pipeline_counts.get(j.status, 0) + 1
    
    # Get tomorrow's follow-ups
    tomorrow = today + timedelta(days=1)
    tomorrow_followups = (
        await db.execute(
            select(Contact).where(
                Contact.user_id == current_user.id,
                Contact.is_deleted.is_(False),
                Contact.follow_up_date == tomorrow,
            )
        )
    ).scalars().all()
    
    data = {
        "today_log": log_data,
        "last_7_days_trend": last_7_days,
        "active_pipeline": pipeline_counts,
        "followups_due_tomorrow": [
            {"name": c.name, "company": c.company}
            for c in tomorrow_followups
        ],
    }
    
    priorities = await generate_weekly_review(data)  # Reuse for now, can create specific function
    
    return {
        "log_saved": True,
        "log_date": today.isoformat(),
        "priorities": priorities or "Great work today! Keep the momentum going tomorrow.",
        "generated_at": today.isoformat(),
    }


@router.get("/weekly")
async def get_weekly_review(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate comprehensive weekly review with AI analysis."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    # Get this week's daily logs
    logs = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.log_date >= week_start,
                DailyLog.log_date <= week_end,
            )
        )
    ).scalars().all()
    
    # Get this week's job activities
    jobs_this_week = (
        await db.execute(
            select(Job).where(
                Job.user_id == current_user.id,
                Job.is_deleted.is_(False),
                Job.created_at >= week_start,
            )
        )
    ).scalars().all()
    
    # Calculate metrics
    total_applied = sum(log.jobs_applied for log in logs)
    total_connections = sum(log.connections_sent for log in logs)
    total_comments = sum(log.comments_made for log in logs)
    total_calls = sum(log.networking_calls for log in logs)
    total_referrals = sum(log.referrals_asked for log in logs)
    posts_published = sum(1 for log in logs if log.post_published)
    avg_energy = sum(log.energy_level for log in logs if log.energy_level) / len([l for l in logs if l.energy_level]) if any(l.energy_level for l in logs) else None
    
    # Get previous week for comparison
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = prev_week_start + timedelta(days=6)
    prev_logs = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.log_date >= prev_week_start,
                DailyLog.log_date <= prev_week_end,
            )
        )
    ).scalars().all()
    
    prev_total_applied = sum(log.jobs_applied for log in prev_logs)
    
    # Pipeline changes
    new_applications = len(jobs_this_week)
    status_changes = []  # Would need to track status history
    
    data = {
        "week": {
            "start": week_start.isoformat(),
            "end": week_end.isoformat(),
            "number": week_start.isocalendar().week,
        },
        "daily_logs": [
            {
                "date": log.log_date.isoformat(),
                "jobs_applied": log.jobs_applied,
                "connections_sent": log.connections_sent,
                "comments_made": log.comments_made,
                "energy_level": log.energy_level,
                "mood": log.mood,
            }
            for log in logs
        ],
        "totals": {
            "jobs_applied": total_applied,
            "connections_sent": total_connections,
            "comments_made": total_comments,
            "networking_calls": total_calls,
            "referrals_asked": total_referrals,
            "posts_published": posts_published,
            "avg_energy": round(avg_energy, 1) if avg_energy else None,
        },
        "comparison": {
            "prev_week_applied": prev_total_applied,
            "change": total_applied - prev_total_applied,
        },
        "pipeline": {
            "new_applications": new_applications,
            "status_changes": status_changes,
        },
    }
    
    review = await generate_weekly_review(data)
    
    # Save metrics to weekly_metrics table
    metrics = WeeklyMetrics(
        user_id=current_user.id,
        week_number=week_start.isocalendar().week,
        week_start=week_start,
        week_end=week_end,
        total_applied=total_applied,
        total_connections=total_connections,
        total_calls=total_calls,
        total_referrals=total_referrals,
        posts_published=posts_published,
        interviews_scheduled=0,  # Would need to count from jobs
        response_rate=None,  # Would need to calculate
        ai_analysis=review,
    )
    db.add(metrics)
    await db.commit()
    
    return {
        "review": review or "Weekly review unavailable at this time.",
        "metrics": {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "total_applied": total_applied,
            "total_connections": total_connections,
            "avg_energy": avg_energy,
            "posts_published": posts_published,
        },
        "generated_at": today.isoformat(),
    }
