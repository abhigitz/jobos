from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class JDKeyword(Base, IDMixin, TimestampMixin):
    __tablename__ = "jd_keywords"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency_count: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    in_profile_dna: Mapped[bool] = mapped_column(Boolean, default=False)
    gap_flagged_date: Mapped[Optional[date]] = mapped_column(Date())
    addressed_date: Mapped[Optional[date]] = mapped_column(Date())
