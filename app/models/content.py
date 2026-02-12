from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class ContentCalendar(Base, IDMixin, TimestampMixin):
    __tablename__ = "content_calendar"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_date: Mapped[datetime] = mapped_column(Date(), nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(String(500))
    category: Mapped[Optional[str]] = mapped_column(String(50))
    draft_text: Mapped[Optional[str]] = mapped_column(Text)
    final_text: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="Planned")
    post_url: Mapped[Optional[str]] = mapped_column(String(1000))
    likes: Mapped[Optional[int]] = mapped_column(Integer)
    comments: Mapped[Optional[int]] = mapped_column(Integer)
    reposts: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "status IN ('Planned', 'Drafted', 'Reviewed', 'Published')",
            name="ck_content_status_valid",
        ),
    )
