from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ContactCreate(BaseModel):
    name: str = Field(..., max_length=255)
    company: Optional[str] = None
    their_role: Optional[str] = None
    connection_type: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None


class ContactUpdate(BaseModel):
    company: Optional[str] = None
    their_role: Optional[str] = None
    connection_type: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    reached_out_date: Optional[date] = None
    response: Optional[str] = None
    follow_up_date: Optional[date] = None
    referral_status: Optional[str] = None
    notes: Optional[str] = None
    is_deleted: Optional[bool] = None


class ContactOut(BaseModel):
    id: UUID
    name: str
    company: Optional[str]
    their_role: Optional[str]
    referral_status: str

    class Config:
        from_attributes = True
