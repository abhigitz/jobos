from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class ScoutResult(Base, IDMixin, TimestampMixin):
    __tablename__ = "scout_results"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500))
    snippet: Mapped[str | None] = mapped_column(Text)
    salary_raw: Mapped[str | None] = mapped_column(String(200))
    posted_date_raw: Mapped[str | None] = mapped_column(String(100))
    normalized_data: Mapped[dict | None] = mapped_column(JSONB)
    fit_score: Mapped[float | None] = mapped_column(Float)
    b2c_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_reasoning: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), server_default="new")
    promoted_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    scout_run_id: Mapped[str | None] = mapped_column(String(50))

    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'reviewed', 'promoted', 'dismissed')",
            name="ck_scout_results_status_valid",
        ),
    )
