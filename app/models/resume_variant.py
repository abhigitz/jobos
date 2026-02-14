from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin
from .types import StringArray


class ResumeVariant(Base, IDMixin, TimestampMixin):
    __tablename__ = "resume_variants"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    variant_name: Mapped[Optional[str]] = mapped_column(String(255))
    target_role_type: Mapped[Optional[str]] = mapped_column(String(255))
    customizations_made: Mapped[Optional[str]] = mapped_column(Text)
    ats_keywords: Mapped[Optional[List[str]]] = mapped_column(StringArray())
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    response_rate: Mapped[Optional[float]]
