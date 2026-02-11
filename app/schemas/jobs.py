from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class JDAnalyzeRequest(BaseModel):
    jd_text: str = Field(..., min_length=100, max_length=15000)
    jd_url: Optional[str] = Field(None, max_length=1000)


class JobCreate(BaseModel):
    company_name: str = Field(..., max_length=255, alias="company")
    role_title: str = Field(..., max_length=255, alias="role")
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None
    source_portal: Optional[str] = Field("Direct", max_length=100)
    status: str = "Applied"
    fit_score: Optional[float] = None
    ats_score: Optional[float] = None
    resume_version: Optional[str] = None
    apply_type: Optional[str] = Field("quick", max_length=10)
    referral_contact: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {
            "Analyzed",
            "Applied",
            "Screening",
            "Interview Scheduled",
            "Interview Done",
            "Offer",
            "Rejected",
            "Withdrawn",
            "Ghosted",
        }
        if v not in allowed:
            raise ValueError("Invalid status")
        return v

    @field_validator("fit_score")
    @classmethod
    def validate_fit_score(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 10.0):
            raise ValueError("fit_score must be between 0 and 10")
        return v

    @field_validator("ats_score")
    @classmethod
    def validate_ats_score(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("ats_score must be between 0 and 100")
        return v

    @field_validator("apply_type")
    @classmethod
    def validate_apply_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"quick", "deep"}:
            raise ValueError("apply_type must be 'quick' or 'deep'")
        return v


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

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {
            "Analyzed",
            "Applied",
            "Screening",
            "Interview Scheduled",
            "Interview Done",
            "Offer",
            "Rejected",
            "Withdrawn",
            "Ghosted",
        }
        if v not in allowed:
            raise ValueError("Invalid status")
        return v


class JobOut(BaseModel):
    id: UUID
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
