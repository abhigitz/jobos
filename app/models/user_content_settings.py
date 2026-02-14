from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin
from .types import JSONBCompat


class UserContentSettings(Base, IDMixin, TimestampMixin):
    __tablename__ = "user_content_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    categories: Mapped[list] = mapped_column(
        JSONBCompat(),
        default=lambda: ["Growth", "Career", "Leadership", "GenAI", "Industry", "Personal"],
    )

    weekly_post_goal: Mapped[int] = mapped_column(Integer, default=5)

    avoid_specific_numbers: Mapped[bool] = mapped_column(Boolean, default=True)
