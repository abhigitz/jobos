from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class ProfileDNA(Base, IDMixin, TimestampMixin):
    __tablename__ = "profile_dna"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    full_name: Mapped[str | None] = mapped_column(String(255))
    positioning_statement: Mapped[str | None] = mapped_column(Text)
    target_roles: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    target_locations: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    target_salary_range: Mapped[str | None] = mapped_column(String(100))
    core_skills: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    tools_platforms: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    industries: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    achievements: Mapped[dict | None] = mapped_column(JSONB, default=list)
    resume_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    education: Mapped[dict | None] = mapped_column(JSONB, default=list)
    alumni_networks: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    career_narrative: Mapped[str | None] = mapped_column(Text)
    raw_resume_text: Mapped[str | None] = mapped_column(Text)
    experience_level: Mapped[str | None] = mapped_column(String(50))
    years_of_experience: Mapped[int | None]
    job_search_type: Mapped[str | None] = mapped_column(String(50))
    lane_labels: Mapped[dict | None] = mapped_column(
        JSONB,
        default={
            "1": "Dream Companies",
            "2": "Good Fit",
            "3": "Backup Options",
        },
    )
