from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IDMixin

if TYPE_CHECKING:
    from .contact import Contact
    from .job import Job


class ActivityLog(Base, IDMixin):
    __tablename__ = "activity_log"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    related_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True
    )
    related_contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    job: Mapped[Optional["Job"]] = relationship("Job", foreign_keys=[related_job_id], lazy="selectin")
    contact: Mapped[Optional["Contact"]] = relationship(
        "Contact", foreign_keys=[related_contact_id], lazy="selectin"
    )
