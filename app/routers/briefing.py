from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.content import ContentCalendar
from app.models.daily_log import DailyLog
from app.models.job import Job
from app.models.user import User
from app.services.ai_service import (
    generate_morning_briefing,
    generate_midday_check,
    generate_weekly_review,
)
from app.services.telegram_service import send_message


router = APIRouter()
settings = get_settings()


async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.n8n_api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


async def _active_users(db: AsyncSession):
    rows = (
        await db.execute(
            select(User).where(User.is_active.is_(True), User.telegram_chat_id.is_not(None))
        )
    ).scalars().all()
    return rows


@router.post("/morning")
async def morning_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    today = date.today()
    for user in users:
        jobs = (
            await db.execute(
                select(Job).where(Job.user_id == user.id, Job.is_deleted.is_(False))
            )
        ).scalars().all()
        logs = (
            await db.execute(
                select(DailyLog).where(DailyLog.user_id == user.id)
            )
        ).scalars().all()
        data = {"jobs": [j.status for j in jobs], "logs": [l.log_date for l in logs], "today": today}
        text = await generate_morning_briefing(data)
        if text:
            await send_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
    return {"status": "ok"}


@router.post("/midday")
async def midday_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    for user in users:
        logs = (
            await db.execute(
                select(DailyLog).where(DailyLog.user_id == user.id)
            )
        ).scalars().all()
        data = {"logs": [l.jobs_applied for l in logs]}
        text = await generate_midday_check(data)
        if text:
            await send_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
    return {"status": "ok"}


@router.post("/evening-prompt")
async def evening_prompt(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    for user in users:
        text = (
            "Evening check-in\n\n"
            "1. How many roles did you apply to today?\n"
            "2. How many new connections did you start?\n"
            "3. Any interviews scheduled?\n"
            "4. What's your top priority for tomorrow?"
        )
        await send_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
    return {"status": "ok"}


@router.post("/content-draft")
async def content_draft_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    from app.services.ai_service import generate_content_draft
    from app.models.profile import ProfileDNA

    users = await _active_users(db)
    tomorrow = date.today() + timedelta(days=1)
    for user in users:
        item = (
            await db.execute(
                select(ContentCalendar).where(
                    ContentCalendar.user_id == user.id,
                    ContentCalendar.scheduled_date == tomorrow,
                )
            )
        ).scalars().first()
        if not item:
            continue
        prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == user.id))
        profile = prof_res.scalar_one_or_none()
        profile_dict = {}
        if profile is not None:
            profile_dict = {
                "full_name": profile.full_name,
                "positioning_statement": profile.positioning_statement,
                "target_roles": profile.target_roles,
            }
        draft = await generate_content_draft(item.topic or "", item.category or "", profile_dict)
        if draft:
            item.draft_text = draft
            item.status = "Drafted"
            await db.commit()
            await send_message(user.telegram_chat_id, draft)  # type: ignore[arg-type]
    return {"status": "ok"}


@router.post("/weekly-review")
async def weekly_review_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    for user in users:
        logs = (
            await db.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
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
                }
                for l in logs
            ]
        }
        text = await generate_weekly_review(data)
        if text:
            await send_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
    return {"status": "ok"}
