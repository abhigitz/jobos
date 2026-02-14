from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContactCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "John Smith",
                    "company": "Acme Corp",
                    "their_role": "VP Product",
                    "connection_type": "Direct",
                    "follow_up_date": "2025-02-20",
                }
            ]
        }
    )
    name: str = Field(..., max_length=255)
    company: Optional[str] = None
    their_role: Optional[str] = None
    connection_type: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    follow_up_date: Optional[date] = None
    referral_status: Optional[str] = None
    notes: Optional[str] = None


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
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "name": "John Smith",
                    "company": "Acme Corp",
                    "their_role": "VP Product",
                    "connection_type": "Direct",
                    "referral_status": "Pending",
                }
            ]
        },
    )
    id: UUID
    name: str
    company: Optional[str]
    their_role: Optional[str]
    connection_type: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    reached_out_date: Optional[date] = None
    response: Optional[str] = None
    follow_up_date: Optional[date] = None
    referral_status: str
    last_outreach_date: Optional[date] = None
    outreach_notes: Optional[str] = None
    notes: Optional[str] = None
