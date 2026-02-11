from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class JDAnalyzeRequest(BaseModel):
    jd_text: str = Field(..., min_length=100, max_length=15000)
    jd_url: Optional[str] = Field(None, max_length=1000)


class JobCreate(BaseModel):
    company_name: str = Field(..., max_length=255)
    role_title: str = Field(..., max_length=255)
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None
    source_portal: Optional[str] = None
    status: str = "Discovered"
    referral_contact: Optional[str] = None
    notes: Optional[str] = None


class JobUpdate(BaseModel):
    status: Optional[str] = None
    interview_date: Optional[datetime] = None
    interview_type: Optional[str] = None
    interviewer_name: Optional[str] = None
    interviewer_linkedin: Optional[str] = None
    prep_notes: Optional[str] = None
    interview_feedback: Optional[str] = None
    notes: Optional[str] = None
    resume_version: Optional[str] = None
    applied_date: Optional[date] = None


class JobOut(BaseModel):
    id: str
    company_name: str
    role_title: str
    status: str
    fit_score: Optional[float] = None
    ats_score: Optional[float] = None
    source_portal: Optional[str] = None
    applied_date: Optional[date] = None
    interview_date: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int
