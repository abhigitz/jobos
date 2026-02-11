from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class DailyLogIn(BaseModel):
    log_date: date
    jobs_applied: int
    connections_sent: int
    comments_made: int
    post_published: bool
    networking_calls: int
    referrals_asked: int
    naukri_updated: bool
    deep_dive_company: Optional[str] = None
    hours_spent: Optional[float] = None
    self_rating: Optional[int] = None
    key_win: Optional[str] = None
    tomorrow_priorities: Optional[str] = None


class DailyLogOut(BaseModel):
    id: UUID
    log_date: date
    jobs_applied: int
    connections_sent: int
    comments_made: int
    post_published: bool
    networking_calls: int
    referrals_asked: int
    naukri_updated: bool

    class Config:
        from_attributes = True


class WeeklyReviewOut(BaseModel):
    id: UUID
    week_number: Optional[int]
    week_start: Optional[date]
    week_end: Optional[date]
    total_applied: int
    total_connections: int
    total_calls: int
    total_referrals: int
    posts_published: int
    interviews_scheduled: int
    response_rate: Optional[float]
    ai_analysis: Optional[str]

    class Config:
        from_attributes = True


class DashboardOut(BaseModel):
    total_applied: int
    total_interviews: int
    pipeline_breakdown: dict
    this_week: dict
    streak_days: int
    top_companies: list[str]
    follow_ups_due_today: int
    next_interview: Optional[dict]
