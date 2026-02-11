from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    name: str = Field(..., max_length=255)
    lane: int
    stage: Optional[str] = Field(None, max_length=50)
    sector: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)
    b2c_validated: Optional[bool] = None
    hq_city: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class CompanyUpdate(BaseModel):
    lane: Optional[int] = None
    stage: Optional[str] = None
    sector: Optional[str] = None
    website: Optional[str] = None
    b2c_validated: Optional[bool] = None
    hq_city: Optional[str] = None
    is_excluded: Optional[bool] = None
    deep_dive_content: Optional[str] = None
    notes: Optional[str] = None


class CompanyOut(BaseModel):
    id: UUID
    name: str
    lane: int
    stage: Optional[str]
    sector: Optional[str]
    website: Optional[str] = None
    b2c_validated: bool = False
    hq_city: Optional[str] = None
    is_excluded: bool = False
    deep_dive_done: bool = False
    deep_dive_content: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class CompanySearchResult(BaseModel):
    id: UUID
    name: str
    lane: int
    sector: Optional[str] = None
    hq_city: Optional[str] = None

    class Config:
        from_attributes = True
