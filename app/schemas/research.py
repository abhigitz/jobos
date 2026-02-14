from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    """Request body for starting new company research."""

    company_name: str = Field(..., min_length=1, max_length=255)
    custom_questions: Optional[str] = Field(None, max_length=5000)


class ResearchResponse(BaseModel):
    """Response model for company research."""

    id: UUID
    company_name: str
    status: str
    research_data: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True
