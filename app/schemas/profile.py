from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    positioning_statement: Optional[str] = None
    target_roles: Optional[list[str]] = None
    target_locations: Optional[list[str]] = None
    target_salary_range: Optional[str] = None
    core_skills: Optional[list[str]] = None
    tools_platforms: Optional[list[str]] = None
    industries: Optional[list[str]] = None
    experience_level: Optional[str] = None
    years_of_experience: Optional[int] = None
    job_search_type: Optional[str] = None
    achievements: Optional[list[dict]] = None
    resume_keywords: Optional[list[str]] = None
    education: Optional[list[dict]] = None
    alumni_networks: Optional[list[str]] = None
    career_narrative: Optional[str] = None
    raw_resume_text: Optional[str] = None
    lane_labels: Optional[dict] = None


class ProfileExtractRequest(BaseModel):
    resume_text: str = Field(..., min_length=500)


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: Optional[str] = None
    positioning_statement: Optional[str] = None
    target_roles: Optional[list[str]] = None
    target_locations: Optional[list[str]] = None
    target_salary_range: Optional[str] = None
    core_skills: Optional[list[str]] = None
    tools_platforms: Optional[list[str]] = None
    industries: Optional[list[str]] = None
    achievements: Optional[list[dict]] = None
    resume_keywords: Optional[list[str]] = None
    education: Optional[list[dict]] = None
    alumni_networks: Optional[list[str]] = None
    career_narrative: Optional[str] = None
    raw_resume_text: Optional[str] = None
    experience_level: Optional[str] = None
    years_of_experience: Optional[int] = None
    job_search_type: Optional[str] = None
    lane_labels: Optional[dict] = None
