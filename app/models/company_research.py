from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class CompanyResearch(Base, IDMixin, TimestampMixin):
    """Stores AI-generated company deep research for interview preparation."""

    __tablename__ = "company_researches"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    custom_questions: Mapped[Optional[str]] = mapped_column(Text)
    research_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", server_default="pending"
    )
