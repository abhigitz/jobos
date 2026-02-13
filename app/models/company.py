from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class Company(Base, IDMixin, TimestampMixin):
    __tablename__ = "companies"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lane: Mapped[Optional[int]]
    stage: Mapped[Optional[str]] = mapped_column(String(50))
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    b2c_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    funding: Mapped[Optional[str]] = mapped_column(Text)
    hq_city: Mapped[Optional[str]] = mapped_column(String(100))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    open_roles_count: Mapped[int] = mapped_column(Integer, default=0)
    last_researched: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deep_dive_done: Mapped[bool] = mapped_column(Boolean, default=False)
    deep_dive_content: Mapped[Optional[str]] = mapped_column(Text)
    investors: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String))
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("lane IN (1, 2, 3, 4, 5)", name="ck_companies_lane_valid"),
    )
