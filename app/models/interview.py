from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class Interview(Base, IDMixin, TimestampMixin):
    __tablename__ = "interviews"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    interview_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    round: Mapped[str] = mapped_column(String(100), default="Phone Screen")
    interviewer_name: Mapped[Optional[str]] = mapped_column(String(255))
    interviewer_role: Mapped[Optional[str]] = mapped_column(String(255))
    interviewer_linkedin: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50), default="Scheduled")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    questions_asked: Mapped[Optional[str]] = mapped_column(Text)
    went_well: Mapped[Optional[str]] = mapped_column(Text)
    to_improve: Mapped[Optional[str]] = mapped_column(Text)
    next_steps: Mapped[Optional[str]] = mapped_column(Text)
    prep_content: Mapped[Optional[str]] = mapped_column(Text)
    prep_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('Scheduled', 'Completed', 'Cancelled', 'No-show')",
            name="ck_interviews_status_valid",
        ),
        CheckConstraint(
            "rating BETWEEN 1 AND 10",
            name="ck_interviews_rating_range",
        ),
    )
