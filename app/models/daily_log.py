from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class DailyLog(Base, IDMixin, TimestampMixin):
    __tablename__ = "daily_log"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    log_date: Mapped[date] = mapped_column(Date(), nullable=False)
    jobs_applied: Mapped[int] = mapped_column(Integer, default=0)
    connections_sent: Mapped[int] = mapped_column(Integer, default=0)
    comments_made: Mapped[int] = mapped_column(Integer, default=0)
    post_published: Mapped[bool] = mapped_column(Boolean, default=False)
    networking_calls: Mapped[int] = mapped_column(Integer, default=0)
    referrals_asked: Mapped[int] = mapped_column(Integer, default=0)
    naukri_updated: Mapped[bool] = mapped_column(Boolean, default=False)
    deep_dive_company: Mapped[str | None] = mapped_column(String(255))
    hours_spent: Mapped[float | None]
    self_rating: Mapped[int | None]
    key_win: Mapped[str | None] = mapped_column(Text)
    tomorrow_priorities: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_daily_log_user_date"),
        CheckConstraint("self_rating BETWEEN 1 AND 10", name="ck_daily_log_self_rating_range"),
    )
