from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class WeeklyMetrics(Base, IDMixin, TimestampMixin):
    __tablename__ = "weekly_metrics"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    week_number: Mapped[Optional[int]]
    week_start: Mapped[Optional[date]] = mapped_column(Date())
    week_end: Mapped[Optional[date]] = mapped_column(Date())
    total_applied: Mapped[int] = mapped_column(Integer, default=0)
    total_connections: Mapped[int] = mapped_column(Integer, default=0)
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_referrals: Mapped[int] = mapped_column(Integer, default=0)
    posts_published: Mapped[int] = mapped_column(Integer, default=0)
    interviews_scheduled: Mapped[int] = mapped_column(Integer, default=0)
    response_rate: Mapped[Optional[float]]
    whats_working: Mapped[Optional[str]] = mapped_column(Text)
    whats_not: Mapped[Optional[str]] = mapped_column(Text)
    key_adjustment: Mapped[Optional[str]] = mapped_column(Text)
    ai_analysis: Mapped[Optional[str]] = mapped_column(Text)
