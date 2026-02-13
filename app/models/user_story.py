from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin


class UserStory(Base, IDMixin):
    __tablename__ = "user_stories"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    prompt_question: Mapped[Optional[str]] = mapped_column(Text)
    story_text: Mapped[str] = mapped_column(Text, nullable=False)
    company_context: Mapped[Optional[str]] = mapped_column(String(100))
    theme: Mapped[Optional[str]] = mapped_column(String(50))

    used_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_user_stories_user_id", "user_id"),)
