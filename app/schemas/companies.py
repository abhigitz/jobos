from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CompanyCreate(BaseModel):
    name: str = Field(..., max_length=255)
    lane: int
    stage: Optional[str] = Field(None, max_length=50)
    sector: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)
    b2c_validated: Optional[bool] = None
    hq_city: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class CompanyQuickCreate(BaseModel):
    """Minimal company creation from JD analysis flow."""
    name: str = Field(..., max_length=255)
    lane: int = Field(2, ge=1, le=3)
    sector: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)


class CompanyUpdate(BaseModel):
    lane: Optional[int] = None
    stage: Optional[str] = None
    sector: Optional[str] = None
    website: Optional[str] = None
    b2c_validated: Optional[bool] = None
    hq_city: Optional[str] = None
    funding: Optional[str] = None
    investors: Optional[list[str]] = None
    is_excluded: Optional[bool] = None
    deep_dive_content: Optional[str] = None
    notes: Optional[str] = None


class CompanyOut(BaseModel):
    id: UUID
    name: str
    lane: Optional[int] = None
    lane_label: Optional[str] = None
    stage: Optional[str]
    sector: Optional[str]
    website: Optional[str] = None
    b2c_validated: bool = False
    hq_city: Optional[str] = None
    funding: Optional[str] = None
    investors: Optional[list[str]] = None
    is_excluded: bool = False
    deep_dive_done: bool = False
    deep_dive_content: Optional[str] = None
    last_researched: Optional[datetime] = None
    notes: Optional[str] = None

    @model_validator(mode='after')
    def compute_lane_label(self):
        LANE_LABELS = {
            1: "Late-stage / Pre-IPO",
            2: "Growth-stage (Series C-D)",
            3: "MNC / Large Indian Corps",
        }
        if self.lane is not None:
            self.lane_label = LANE_LABELS.get(self.lane, f"Lane {self.lane}")
        return self

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
