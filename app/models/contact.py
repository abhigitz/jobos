from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class Contact(Base, IDMixin, TimestampMixin):
    __tablename__ = "contacts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255))
    their_role: Mapped[str | None] = mapped_column(String(255))
    connection_type: Mapped[str | None] = mapped_column(String(100))
    linkedin_url: Mapped[str | None] = mapped_column(String(1000))
    email: Mapped[str | None] = mapped_column(String(255))
    reached_out_date: Mapped[datetime | None] = mapped_column(Date())
    response: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[datetime | None] = mapped_column(Date())
    referral_status: Mapped[str] = mapped_column(String(50), default="Identified")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "referral_status IN ('Identified', 'Reached_Out', 'Intro_Made', 'Referral_Submitted', 'Outcome')",
            name="ck_contacts_referral_status_valid",
        ),
    )
