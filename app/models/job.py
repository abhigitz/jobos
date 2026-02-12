from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class Job(Base, IDMixin, TimestampMixin):
    __tablename__ = "jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_title: Mapped[str] = mapped_column(String(255), nullable=False)
    jd_text: Mapped[Optional[str]] = mapped_column(Text)
    jd_url: Mapped[Optional[str]] = mapped_column(String(1000))
    source_portal: Mapped[Optional[str]] = mapped_column(String(100))
    fit_score: Mapped[Optional[float]]
    ats_score: Mapped[Optional[float]]
    status: Mapped[str] = mapped_column(String(50), default="Tracking")
    resume_version: Mapped[Optional[str]] = mapped_column(String(100))
    apply_type: Mapped[Optional[str]] = mapped_column(String(10))
    cover_letter: Mapped[Optional[str]] = mapped_column(Text)
    referral_contact: Mapped[Optional[str]] = mapped_column(String(255))
    application_channel: Mapped[Optional[str]] = mapped_column(String(50))
    closed_reason: Mapped[Optional[str]] = mapped_column(String(50))
    keywords_matched: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    keywords_missing: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    ai_analysis: Mapped[Optional[Dict]] = mapped_column(JSONB)
    fit_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    salary_range: Mapped[Optional[str]] = mapped_column(String(100))
    resume_suggestions: Mapped[Optional[list]] = mapped_column(JSONB)
    interview_angle: Mapped[Optional[str]] = mapped_column(Text)
    b2c_check: Mapped[Optional[bool]] = mapped_column(Boolean)
    b2c_reason: Mapped[Optional[str]] = mapped_column(String(200))
    applied_date: Mapped[Optional[date]] = mapped_column(Date())
    interview_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    interview_type: Mapped[Optional[str]] = mapped_column(String(50))
    interviewer_name: Mapped[Optional[str]] = mapped_column(String(255))
    interviewer_linkedin: Mapped[Optional[str]] = mapped_column(String(1000))
    prep_notes: Mapped[Optional[str]] = mapped_column(Text)
    interview_feedback: Mapped[Optional[str]] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[list]] = mapped_column(JSONB, server_default='[]', default=list)
    last_followup_date: Mapped[Optional[date]] = mapped_column(Date())
    followup_count: Mapped[int] = mapped_column(Integer, default=0)
    followup_date: Mapped[Optional[date]] = mapped_column(Date())

    __table_args__ = (
        CheckConstraint(
            "status IN ('Tracking', 'Applied', 'Interview', 'Offer', 'Closed')",
            name="ck_jobs_status_valid",
        ),
    )
