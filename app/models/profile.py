from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class ProfileDNA(Base, IDMixin, TimestampMixin):
    __tablename__ = "profile_dna"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    positioning_statement: Mapped[Optional[str]] = mapped_column(Text)
    target_roles: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    target_locations: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    target_salary_range: Mapped[Optional[str]] = mapped_column(String(100))
    core_skills: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    tools_platforms: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    industries: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    achievements: Mapped[Optional[Dict]] = mapped_column(JSONB, default=list)
    resume_keywords: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    education: Mapped[Optional[Dict]] = mapped_column(JSONB, default=list)
    alumni_networks: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    career_narrative: Mapped[Optional[str]] = mapped_column(Text)
    raw_resume_text: Mapped[Optional[str]] = mapped_column(Text)
    experience_level: Mapped[Optional[str]] = mapped_column(String(50))
    years_of_experience: Mapped[Optional[int]]
    job_search_type: Mapped[Optional[str]] = mapped_column(String(50))
    lane_labels: Mapped[Optional[Dict]] = mapped_column(
        JSONB,
        default={
            "1": "Dream Companies",
            "2": "Good Fit",
            "3": "Backup Options",
        },
    )
