from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class ContentCreate(BaseModel):
    scheduled_date: date
    topic: str = Field(..., max_length=500)
    category: Optional[str] = Field(None, max_length=50)


class ContentUpdate(BaseModel):
    topic: Optional[str] = None
    category: Optional[str] = None
    draft_text: Optional[str] = None
    final_text: Optional[str] = None
    status: Optional[str] = None
    post_url: Optional[str] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    reposts: Optional[int] = None


class ContentOut(BaseModel):
    id: str
    scheduled_date: date
    topic: Optional[str]
    category: Optional[str]
    status: str

    class Config:
        from_attributes = True
