from typing import Optional

from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    name: str = Field(..., max_length=255)
    lane: int
    stage: Optional[str] = Field(None, max_length=50)
    sector: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)


class CompanyUpdate(BaseModel):
    lane: Optional[int] = None
    stage: Optional[str] = None
    sector: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None


class CompanyOut(BaseModel):
    id: str
    name: str
    lane: int
    stage: Optional[str]
    sector: Optional[str]

    class Config:
        from_attributes = True
