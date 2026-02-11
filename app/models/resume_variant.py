from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class ResumeVariant(Base, IDMixin, TimestampMixin):
    __tablename__ = "resume_variants"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    variant_name: Mapped[str | None] = mapped_column(String(255))
    target_role_type: Mapped[str | None] = mapped_column(String(255))
    customizations_made: Mapped[str | None] = mapped_column(Text)
    ats_keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    response_rate: Mapped[float | None]
