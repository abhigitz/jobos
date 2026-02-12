from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class Job(Base, IDMixin, TimestampMixin):
    __tablename__ = "jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_title: Mapped[str] = mapped_column(String(255), nullable=False)
    jd_text: Mapped[str | None] = mapped_column(Text)
    jd_url: Mapped[str | None] = mapped_column(String(1000))
    source_portal: Mapped[str | None] = mapped_column(String(100))
    fit_score: Mapped[float | None]
    ats_score: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(50), default="Tracking")
    resume_version: Mapped[str | None] = mapped_column(String(100))
    apply_type: Mapped[str | None] = mapped_column(String(10))
    cover_letter: Mapped[str | None] = mapped_column(Text)
    referral_contact: Mapped[str | None] = mapped_column(String(255))
    application_channel: Mapped[str | None] = mapped_column(String(50))
    closed_reason: Mapped[str | None] = mapped_column(String(50))
    keywords_matched: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    keywords_missing: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB)
    fit_reasoning: Mapped[str | None] = mapped_column(Text)
    salary_range: Mapped[str | None] = mapped_column(String(100))
    applied_date: Mapped[date | None] = mapped_column(Date())
    interview_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interview_type: Mapped[str | None] = mapped_column(String(50))
    interviewer_name: Mapped[str | None] = mapped_column(String(255))
    interviewer_linkedin: Mapped[str | None] = mapped_column(String(1000))
    prep_notes: Mapped[str | None] = mapped_column(Text)
    interview_feedback: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[list | None] = mapped_column(JSONB, server_default='[]', default=list)
    last_followup_date: Mapped[date | None] = mapped_column(Date())
    followup_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        CheckConstraint(
            "status IN ('Tracking', 'Applied', 'Interview', 'Offer', 'Closed')",
            name="ck_jobs_status_valid",
        ),
    )
