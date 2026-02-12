from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

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
    company: Mapped[Optional[str]] = mapped_column(String(255))
    their_role: Mapped[Optional[str]] = mapped_column(String(255))
    connection_type: Mapped[Optional[str]] = mapped_column(String(100))
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(1000))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    reached_out_date: Mapped[Optional[date]] = mapped_column(Date())
    response: Mapped[Optional[str]] = mapped_column(Text)
    follow_up_date: Mapped[Optional[date]] = mapped_column(Date())
    referral_status: Mapped[str] = mapped_column(String(50), default="Identified")
    last_outreach_date: Mapped[Optional[date]] = mapped_column(Date())
    outreach_notes: Mapped[Optional[str]] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "referral_status IN ('Identified', 'Reached_Out', 'Intro_Made', 'Referral_Submitted', 'Outcome')",
            name="ck_contacts_referral_status_valid",
        ),
    )
