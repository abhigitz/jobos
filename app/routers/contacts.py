from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.contact import Contact
from app.schemas.contacts import ContactCreate, ContactOut, ContactUpdate
from app.services.activity_log import log_activity


router = APIRouter()

VALID_CONNECTION_TYPES = {"IIT-D", "IIM-C", "GrowthX", "Pocket FM", "VC", "Headhunter", "Direct", "Other"}


class OutreachAction(BaseModel):
    action: str
    response: Optional[str] = None
    new_follow_up_date: Optional[date] = None


@router.get("", response_model=list[ContactOut])
async def list_contacts(
    company: Optional[str] = None,
    referral_status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    conditions = [Contact.user_id == current_user.id, Contact.is_deleted.is_(False)]
    if company:
        conditions.append(Contact.company == company)
    if referral_status:
        conditions.append(Contact.referral_status == referral_status)
    rows = (
        await db.execute(select(Contact).where(and_(*conditions)).order_by(Contact.created_at.desc()))
    ).scalars().all()
    return [ContactOut.model_validate(c) for c in rows]


@router.post("", response_model=ContactOut)
async def create_contact(
    payload: ContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ContactOut:
    if payload.connection_type and payload.connection_type not in VALID_CONNECTION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"connection_type must be one of: {', '.join(sorted(VALID_CONNECTION_TYPES))}",
        )

    contact = Contact(user_id=current_user.id, **payload.model_dump())
    db.add(contact)
    await db.commit()
    await db.refresh(contact)

    await log_activity(
        db, current_user.id, "contact_added",
        f"Added contact: {contact.name} at {contact.company or 'N/A'}",
        related_contact_id=contact.id,
    )
    await db.commit()

    return ContactOut.model_validate(contact)


# --- Fixed-path endpoints BEFORE /{id} ---

@router.get("/followups")
async def get_contact_followups(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Contacts with follow_up_date = today or overdue."""
    today = date.today()
    rows = (
        await db.execute(
            select(Contact).where(
                Contact.user_id == current_user.id,
                Contact.is_deleted.is_(False),
                Contact.follow_up_date.is_not(None),
                Contact.follow_up_date <= today,
            ).order_by(Contact.follow_up_date.asc())
        )
    ).scalars().all()

    due_today = []
    overdue = []
    for c in rows:
        entry = {
            "id": str(c.id),
            "name": c.name,
            "company": c.company,
            "connection_type": c.connection_type,
            "follow_up_date": str(c.follow_up_date),
        }
        if c.follow_up_date == today:
            due_today.append(entry)
        else:
            entry["days_overdue"] = (today - c.follow_up_date).days
            overdue.append(entry)

    return {
        "due_today": due_today,
        "overdue": overdue,
        "total": len(due_today) + len(overdue),
    }


@router.get("/follow-ups", response_model=list[ContactOut])
async def follow_ups(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)) -> list[ContactOut]:
    """Legacy endpoint - contacts with follow-ups due."""
    today = date.today()
    rows = (
        await db.execute(
            select(Contact).where(
                Contact.user_id == current_user.id,
                Contact.is_deleted.is_(False),
                Contact.follow_up_date.is_not(None),
                Contact.follow_up_date <= today,
            )
        )
    ).scalars().all()
    return [ContactOut.model_validate(c) for c in rows]


# --- Parametric endpoints ---

@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ContactOut:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.user_id != current_user.id or contact.is_deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    return ContactOut.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: str,
    payload: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ContactOut:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.user_id != current_user.id or contact.is_deleted:
        raise HTTPException(status_code=404, detail="Contact not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)

    await db.commit()
    await db.refresh(contact)
    return ContactOut.model_validate(contact)


@router.delete("/{contact_id}")
async def delete_contact(contact_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)) -> dict:
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.user_id != current_user.id or contact.is_deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact.is_deleted = True
    await db.commit()
    return {"status": "deleted"}


@router.post("/{contact_id}/outreach")
async def log_outreach(
    contact_id: str,
    payload: OutreachAction,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Log an outreach action."""
    contact = await db.get(Contact, contact_id)
    if contact is None or contact.user_id != current_user.id or contact.is_deleted:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact.last_outreach_date = date.today()

    existing_notes = contact.outreach_notes or ""
    separator = "\n---\n" if existing_notes else ""
    contact.outreach_notes = f"{existing_notes}{separator}[{date.today()}] {payload.action}"
    if payload.response:
        contact.outreach_notes += f" — Response: {payload.response}"

    if payload.new_follow_up_date:
        contact.follow_up_date = payload.new_follow_up_date

    await db.commit()
    await db.refresh(contact)

    await log_activity(
        db, current_user.id, "contact_followup",
        f"Outreach to {contact.name} at {contact.company or 'N/A'}: {payload.action}",
        related_contact_id=contact.id,
    )
    await db.commit()

    return {
        "id": str(contact.id),
        "name": contact.name,
        "company": contact.company,
        "last_outreach_date": str(contact.last_outreach_date),
        "follow_up_date": str(contact.follow_up_date) if contact.follow_up_date else None,
    }
