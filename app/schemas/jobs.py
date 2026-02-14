from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JDAnalyzeRequest(BaseModel):
    jd_text: Optional[str] = Field(None, max_length=15000)
    jd_url: Optional[str] = Field(None, max_length=1000)

    @model_validator(mode='after')
    def check_text_or_url(self):
        if not self.jd_text and not self.jd_url:
            raise ValueError("Either jd_text or jd_url must be provided")
        return self


class SaveFromAnalysisRequest(BaseModel):
    """Create a Job from JD analysis results. Called after user sees analysis and decides."""
    company_name: str = Field(..., max_length=255)
    role_title: str = Field(..., max_length=255)
    jd_text: str = Field(..., min_length=50, max_length=15000)
    jd_url: Optional[str] = Field(None, max_length=1000)
    source_portal: str = Field("JD Analysis", max_length=100)
    status: str = Field("Tracking")
    application_channel: Optional[str] = Field(None, max_length=50)
    # Analysis results
    fit_score: Optional[float] = None
    ats_score: Optional[float] = None
    fit_reasoning: Optional[str] = None
    salary_range: Optional[str] = None
    keywords_matched: Optional[list[str]] = None
    keywords_missing: Optional[list[str]] = None
    ai_analysis: Optional[dict] = None
    cover_letter: Optional[str] = None
    resume_suggestions: Optional[list] = None
    interview_angle: Optional[str] = None
    b2c_check: Optional[bool] = None
    b2c_reason: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in ("Tracking", "Applied"):
            raise ValueError("status must be 'Tracking' or 'Applied'")
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


class DeepResumeAnalysisRequest(BaseModel):
    """Deep resume vs JD analysis. Triggered by explicit user request."""
    jd_text: str = Field(..., min_length=100, max_length=15000)
    job_id: Optional[str] = None


class NoteEntry(BaseModel):
    text: str
    created_at: str


class AddNoteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class JobCreate(BaseModel):
    company_name: str = Field(..., max_length=255, alias="company")
    role_title: str = Field(..., max_length=255, alias="role")
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None
    source_portal: Optional[str] = Field("Direct", max_length=100)
    status: str = "Tracking"
    fit_score: Optional[float] = None
    ats_score: Optional[float] = None
    resume_version: Optional[str] = None
    apply_type: Optional[str] = Field("quick", max_length=10)
    referral_contact: Optional[str] = None
    notes: Optional[list[dict]] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {
            "Tracking",
            "Applied",
            "Interview",
            "Offer",
            "Closed",
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
    notes: Optional[list[dict]] = None
    resume_version: Optional[str] = None
    applied_date: Optional[date] = None
    company_name: Optional[str] = Field(None, max_length=255)
    role_title: Optional[str] = Field(None, max_length=255)
    referral_contact: Optional[str] = Field(None, max_length=255)
    application_channel: Optional[str] = Field(None, max_length=50)
    closed_reason: Optional[str] = Field(None, max_length=50)
    fit_reasoning: Optional[str] = None
    salary_range: Optional[str] = Field(None, max_length=100)
    cover_letter: Optional[str] = None
    source_portal: Optional[str] = Field(None, max_length=100)
    jd_url: Optional[str] = Field(None, max_length=1000)
    followup_date: Optional[date] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {
            "Tracking",
            "Applied",
            "Interview",
            "Offer",
            "Closed",
        }
        if v not in allowed:
            raise ValueError("Invalid status")
        return v

    @model_validator(mode='after')
    def default_closed_reason(self):
        if self.status == 'Closed' and self.closed_reason is None:
            self.closed_reason = 'Dropped'
        return self


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: Optional[UUID] = None
    company_name: str
    role_title: str
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None
    source_portal: Optional[str] = None
    fit_score: Optional[float] = None
    ats_score: Optional[float] = None
    status: str
    resume_version: Optional[str] = None
    apply_type: Optional[str] = None
    cover_letter: Optional[str] = None
    referral_contact: Optional[str] = None
    keywords_matched: Optional[list[str]] = None
    keywords_missing: Optional[list[str]] = None
    ai_analysis: Optional[dict] = None
    fit_reasoning: Optional[str] = None
    salary_range: Optional[str] = None
    resume_suggestions: Optional[list] = None
    interview_angle: Optional[str] = None
    b2c_check: Optional[bool] = None
    b2c_reason: Optional[str] = None
    applied_date: Optional[date] = None
    interview_date: Optional[datetime] = None
    interview_type: Optional[str] = None
    interviewer_name: Optional[str] = None
    interviewer_linkedin: Optional[str] = None
    prep_notes: Optional[str] = None
    interview_feedback: Optional[str] = None
    is_deleted: bool = False
    notes: Optional[list[dict]] = None
    application_channel: Optional[str] = None
    closed_reason: Optional[str] = None
    last_followup_date: Optional[date] = None
    followup_count: int = 0
    followup_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int
