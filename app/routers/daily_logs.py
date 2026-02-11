from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.daily_log import DailyLog

router = APIRouter()


class DailyLogCreate(BaseModel):
    log_date: date = Field(default_factory=lambda: date.today())
    jobs_applied: int = Field(default=0, ge=0)
    connections_sent: int = Field(default=0, ge=0)
    comments_made: int = Field(default=0, ge=0)
    post_published: bool = False
    networking_calls: int = Field(default=0, ge=0)
    referrals_asked: int = Field(default=0, ge=0)
    naukri_updated: bool = False
    deep_dive_company: Optional[str] = None
    energy_level: Optional[int] = Field(None, ge=1, le=5)
    mood: Optional[str] = None
    hours_spent: Optional[float] = Field(None, ge=0)
    self_rating: Optional[int] = Field(None, ge=1, le=10)
    key_win: Optional[str] = None
    tomorrow_priorities: Optional[str] = None
    notes: Optional[str] = None


class DailyLogUpdate(BaseModel):
    jobs_applied: Optional[int] = Field(None, ge=0)
    connections_sent: Optional[int] = Field(None, ge=0)
    comments_made: Optional[int] = Field(None, ge=0)
    post_published: Optional[bool] = None
    networking_calls: Optional[int] = Field(None, ge=0)
    referrals_asked: Optional[int] = Field(None, ge=0)
    naukri_updated: Optional[bool] = None
    deep_dive_company: Optional[str] = None
    energy_level: Optional[int] = Field(None, ge=1, le=5)
    mood: Optional[str] = None
    hours_spent: Optional[float] = Field(None, ge=0)
    self_rating: Optional[int] = Field(None, ge=1, le=10)
    key_win: Optional[str] = None
    tomorrow_priorities: Optional[str] = None
    notes: Optional[str] = None


class DailyLogOut(BaseModel):
    id: str
    log_date: date
    jobs_applied: int
    connections_sent: int
    comments_made: int
    post_published: bool
    networking_calls: int
    referrals_asked: int
    naukri_updated: bool
    deep_dive_company: Optional[str] = None
    energy_level: Optional[int] = None
    mood: Optional[str] = None
    hours_spent: Optional[float] = None
    self_rating: Optional[int] = None
    key_win: Optional[str] = None
    tomorrow_priorities: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


def _log_to_out(log: DailyLog) -> DailyLogOut:
    return DailyLogOut(
        id=str(log.id),
        log_date=log.log_date,
        jobs_applied=log.jobs_applied,
        connections_sent=log.connections_sent,
        comments_made=log.comments_made,
        post_published=log.post_published,
        networking_calls=log.networking_calls,
        referrals_asked=log.referrals_asked,
        naukri_updated=log.naukri_updated,
        deep_dive_company=log.deep_dive_company,
        energy_level=log.energy_level,
        mood=log.mood,
        hours_spent=log.hours_spent,
        self_rating=log.self_rating,
        key_win=log.key_win,
        tomorrow_priorities=log.tomorrow_priorities,
        notes=log.notes,
    )


@router.post("", response_model=DailyLogOut, status_code=201)
async def create_or_update_daily_log(
    payload: DailyLogCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> DailyLogOut:
    """Create or update daily log (upsert on user_id + log_date)."""
    existing = await db.execute(
        select(DailyLog).where(
            DailyLog.user_id == current_user.id,
            DailyLog.log_date == payload.log_date,
        )
    )
    existing_log = existing.scalar_one_or_none()

    if existing_log:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(existing_log, field, value)
        log = existing_log
    else:
        log = DailyLog(user_id=current_user.id, **payload.model_dump())
        db.add(log)

    await db.commit()
    await db.refresh(log)
    return _log_to_out(log)


# --- Fixed-path endpoints BEFORE /{date} ---

@router.get("/today")
async def get_today_log(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return today's log if it exists, or null."""
    today = date.today()
    result = await db.execute(
        select(DailyLog).where(
            DailyLog.user_id == current_user.id,
            DailyLog.log_date == today,
        )
    )
    log = result.scalar_one_or_none()
    if log is None:
        return None
    return _log_to_out(log)


@router.get("/streak")
async def get_streak(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return streak days (Sunday-exempt)."""
    today = date.today()
    cutoff = today - timedelta(days=60)

    logs = (
        await db.execute(
            select(DailyLog).where(
                DailyLog.user_id == current_user.id,
                DailyLog.log_date >= cutoff,
            )
        )
    ).scalars().all()
    logs_by_date = {log.log_date: log for log in logs}

    streak = 0
    day_cursor = today
    while True:
        log = logs_by_date.get(day_cursor)
        is_sunday = day_cursor.weekday() == 6

        if log and log.jobs_applied > 0:
            streak += 1
            day_cursor -= timedelta(days=1)
        elif is_sunday:
            day_cursor -= timedelta(days=1)
        else:
            break

    last_logged = None
    if logs:
        last_logged = max(l.log_date for l in logs)

    return {"streak_days": streak, "last_logged": str(last_logged) if last_logged else None}


# --- Parametric endpoints ---

@router.patch("/{log_date}", response_model=DailyLogOut)
async def update_daily_log(
    log_date: date,
    payload: DailyLogUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> DailyLogOut:
    """Update specific fields in an existing daily log."""
    result = await db.execute(
        select(DailyLog).where(
            DailyLog.user_id == current_user.id,
            DailyLog.log_date == log_date,
        )
    )
    log = result.scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="Daily log not found for this date")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(log, field, value)

    await db.commit()
    await db.refresh(log)
    return _log_to_out(log)


@router.get("/{log_date}", response_model=DailyLogOut)
async def get_daily_log(
    log_date: date,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> DailyLogOut:
    """Get daily log for a specific date."""
    result = await db.execute(
        select(DailyLog).where(
            DailyLog.user_id == current_user.id,
            DailyLog.log_date == log_date,
        )
    )
    log = result.scalar_one_or_none()
    if log is None:
        raise HTTPException(status_code=404, detail="Daily log not found for this date")
    return _log_to_out(log)


@router.get("", response_model=list[DailyLogOut])
async def list_daily_logs(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
    days: int = Query(7, ge=1, le=365),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[DailyLogOut]:
    """List daily logs with optional date range filtering."""
    query = select(DailyLog).where(DailyLog.user_id == current_user.id)

    if start_date and end_date:
        query = query.where(
            DailyLog.log_date >= start_date,
            DailyLog.log_date <= end_date,
        )
    else:
        cutoff = date.today() - timedelta(days=days - 1)
        query = query.where(DailyLog.log_date >= cutoff)

    query = query.order_by(DailyLog.log_date.desc())
    result = await db.execute(query)
    logs = result.scalars().all()

    return [_log_to_out(log) for log in logs]
