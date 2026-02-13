from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class UserContentSettings(Base, IDMixin, TimestampMixin):
    __tablename__ = "user_content_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    categories: Mapped[list] = mapped_column(
        JSONB,
        server_default=text(
            "'[\"Growth\", \"Career\", \"Leadership\", \"GenAI\", \"Industry\", \"Personal\"]'::jsonb"
        ),
    )

    weekly_post_goal: Mapped[int] = mapped_column(Integer, default=5)

    avoid_specific_numbers: Mapped[bool] = mapped_column(Boolean, default=True)
