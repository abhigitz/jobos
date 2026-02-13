"""Job scouting models: ScoutedJob, UserScoutPreferences, UserScoutedJob, CompanyCareerSource."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class ScoutedJob(Base, IDMixin, TimestampMixin):
    """Scouted job from external sources (SerpAPI, Greenhouse, Lever, etc.)."""

    __tablename__ = "scouted_jobs"

    external_id: Mapped[Optional[str]] = mapped_column(String(255))
    dedup_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name_normalized: Mapped[Optional[str]] = mapped_column(String(255))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text)
    salary_min: Mapped[Optional[int]] = mapped_column(Integer)
    salary_max: Mapped[Optional[int]] = mapped_column(Integer)
    salary_is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(2000))
    apply_url: Mapped[Optional[str]] = mapped_column(String(2000))
    posted_date: Mapped[Optional[date]] = mapped_column(Date())
    scouted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    inactive_reason: Mapped[Optional[str]] = mapped_column(String(50))
    matched_company_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    raw_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    search_query: Mapped[Optional[str]] = mapped_column(String(255))


class UserScoutPreferences(Base, IDMixin, TimestampMixin):
    """User preferences for job scouting (target roles, locations, companies, etc.)."""

    __tablename__ = "user_scout_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    target_roles: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    role_keywords: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    target_locations: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    location_flexibility: Mapped[str] = mapped_column(String(20), default="preferred")
    target_company_ids: Mapped[List[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, server_default=text("'{}'::uuid[]")
    )
    excluded_company_ids: Mapped[List[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, server_default=text("'{}'::uuid[]")
    )
    target_industries: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    excluded_industries: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    company_stages: Mapped[List[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    min_salary: Mapped[Optional[int]] = mapped_column(Integer)
    salary_flexibility: Mapped[str] = mapped_column(String(20), default="flexible")
    min_score: Mapped[int] = mapped_column(Integer, default=30)
    learned_boosts: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    learned_penalties: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    synced_from_profile_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class UserScoutedJob(Base, IDMixin, TimestampMixin):
    """Association of a scouted job to a user with relevance score and status."""

    __tablename__ = "user_scouted_jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scouted_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scouted_jobs.id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False)
    score_breakdown: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    match_reasons: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text))
    status: Mapped[str] = mapped_column(String(20), default="new")
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    viewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    saved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dismiss_reason: Mapped[Optional[str]] = mapped_column(String(50))
    pipeline_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    added_to_pipeline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("user_id", "scouted_job_id", name="uq_user_scouted_jobs_user_scouted_job"),)


class CompanyCareerSource(Base, IDMixin, TimestampMixin):
    """Career page source for a company (Greenhouse, Lever, Ashby, etc.)."""

    __tablename__ = "company_career_sources"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    careers_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    api_endpoint: Mapped[Optional[str]] = mapped_column(String(2000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    scrape_frequency_hours: Mapped[int] = mapped_column(Integer, default=24)
    scrape_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("company_id", "source_type", name="uq_company_career_sources_company_source"),)
