from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


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
