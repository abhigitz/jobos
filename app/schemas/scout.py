from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# --- Job scouting feature schemas ---

class UserScoutPreferencesOut(BaseModel):
    id: UUID
    user_id: UUID
    target_roles: list[str] = Field(default_factory=list)
    role_keywords: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    location_flexibility: str = "preferred"
    target_company_ids: list[UUID] = Field(default_factory=list)
    excluded_company_ids: list[UUID] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    excluded_industries: list[str] = Field(default_factory=list)
    company_stages: list[str] = Field(default_factory=list)
    min_salary: Optional[int] = None
    salary_flexibility: str = "flexible"
    min_score: int = 30
    learned_boosts: dict[str, Any] = Field(default_factory=dict)
    learned_penalties: dict[str, Any] = Field(default_factory=dict)
    synced_from_profile_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserScoutPreferencesUpdate(BaseModel):
    target_roles: Optional[list[str]] = None
    role_keywords: Optional[list[str]] = None
    target_locations: Optional[list[str]] = None
    location_flexibility: Optional[str] = None
    target_company_ids: Optional[list[UUID]] = None
    excluded_company_ids: Optional[list[UUID]] = None
    target_industries: Optional[list[str]] = None
    excluded_industries: Optional[list[str]] = None
    company_stages: Optional[list[str]] = None
    min_salary: Optional[int] = None
    salary_flexibility: Optional[str] = None
    min_score: Optional[int] = None


class ScoutedJobDetails(BaseModel):
    """Scouted job base details (from ScoutedJob model)."""
    id: UUID
    title: str
    company_name: str
    location: Optional[str] = None
    city: Optional[str] = None
    description: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    source: str
    source_url: Optional[str] = None
    apply_url: Optional[str] = None
    posted_date: Optional[date] = None

    class Config:
        from_attributes = True


class UserScoutedJobOut(BaseModel):
    """User scouted job with score, reasons, and job details."""
    id: UUID
    user_id: UUID
    scouted_job_id: UUID
    relevance_score: int
    score_breakdown: Optional[dict[str, Any]] = None
    match_reasons: Optional[list[str]] = None
    status: str
    matched_at: datetime
    viewed_at: Optional[datetime] = None
    saved_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    dismiss_reason: Optional[str] = None
    pipeline_job_id: Optional[UUID] = None
    added_to_pipeline_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Job details (from ScoutedJob)
    job: ScoutedJobDetails

    class Config:
        from_attributes = True


class ScoutStatsOut(BaseModel):
    new_count: int
    viewed_count: int
    saved_count: int
    dismissed_count: int
    added_to_pipeline_count: int


class DismissRequest(BaseModel):
    reason: str = Field(
        ...,
        description="Dismiss reason: wrong_role, wrong_company, wrong_location, salary_low, already_applied, not_now",
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        valid = {"wrong_role", "wrong_company", "wrong_location", "salary_low", "already_applied", "not_now"}
        if v not in valid:
            raise ValueError(f"reason must be one of: {', '.join(sorted(valid))}")
        return v


# --- Legacy scout results schemas ---

class ScoutResultOut(BaseModel):
    id: UUID
    source: str
    source_url: Optional[str] = None
    title: str
    company_name: str
    location: Optional[str] = None
    snippet: Optional[str] = None
    salary_raw: Optional[str] = None
    posted_date_raw: Optional[str] = None
    fit_score: Optional[float] = None
    b2c_validated: bool = False
    ai_reasoning: Optional[str] = None
    status: str
    promoted_job_id: Optional[UUID] = None
    scout_run_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScoutRunSummary(BaseModel):
    """Summary returned after a scout run completes."""
    run_id: str
    sources_queried: list[str]
    total_fetched: int
    after_dedup: int
    after_prefilter: int
    ai_scored: int
    promoted_to_pipeline: int
    saved_for_review: int
    dismissed: int
    errors: list[str] = Field(default_factory=list)


class ScoutResultsPage(BaseModel):
    items: list[ScoutResultOut]
    total: int
    page: int
    per_page: int
