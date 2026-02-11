from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.contact import Contact
from app.schemas.contacts import ContactCreate, ContactOut, ContactUpdate


router = APIRouter()


@router.get("/", response_model=list[ContactOut])
async def list_contacts(
    company: str | None = None,
    referral_status: str | None = None,
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


@router.post("/", response_model=ContactOut)
async def create_contact(
    payload: ContactCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ContactOut:
    contact = Contact(user_id=current_user.id, **payload.model_dump())
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
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


@router.get("/follow-ups", response_model=list[ContactOut])
async def follow_ups(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)) -> list[ContactOut]:
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
