from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class Job(Base, IDMixin, TimestampMixin):
    __tablename__ = "jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_title: Mapped[str] = mapped_column(String(255), nullable=False)
    jd_text: Mapped[str | None] = mapped_column(Text)
    jd_url: Mapped[str | None] = mapped_column(String(1000))
    source_portal: Mapped[str | None] = mapped_column(String(100))
    fit_score: Mapped[float | None]
    ats_score: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(50), default="Discovered")
    resume_version: Mapped[str | None] = mapped_column(String(100))
    cover_letter: Mapped[str | None] = mapped_column(Text)
    referral_contact: Mapped[str | None] = mapped_column(String(255))
    keywords_matched: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    keywords_missing: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB)
    applied_date: Mapped[datetime | None] = mapped_column(Date())
    interview_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interview_type: Mapped[str | None] = mapped_column(String(50))
    interviewer_name: Mapped[str | None] = mapped_column(String(255))
    interviewer_linkedin: Mapped[str | None] = mapped_column(String(1000))
    prep_notes: Mapped[str | None] = mapped_column(Text)
    interview_feedback: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('Saved', 'Discovered', 'Analyzed', 'Applied', 'Screening', 'Interview_Scheduled', 'Interview_Done', 'Offer', 'Rejected', 'Withdrawn')",
            name="ck_jobs_status_valid",
        ),
    )
