from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class ContentPost(Base, IDMixin, TimestampMixin):
    __tablename__ = "content_posts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    post_text: Mapped[str] = mapped_column(Text, nullable=False)
    topic_title: Mapped[Optional[str]] = mapped_column(Text)
    topic_category: Mapped[Optional[str]] = mapped_column(String(50))

    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer)
    time_of_day: Mapped[Optional[str]] = mapped_column(String(20))

    impressions: Mapped[Optional[int]] = mapped_column(Integer)
    reactions: Mapped[Optional[int]] = mapped_column(Integer)
    comments: Mapped[Optional[int]] = mapped_column(Integer)
    engagement_recorded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    had_image: Mapped[bool] = mapped_column(Boolean, default=False)
    had_carousel: Mapped[bool] = mapped_column(Boolean, default=False)

    generated_by_system: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        Index("ix_content_posts_user_id", "user_id"),
        Index("ix_content_posts_posted_at", "posted_at"),
    )
