from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.content import ContentCalendar
from app.models.profile import ProfileDNA
from app.schemas.content import ContentCreate, ContentOut, ContentUpdate
from app.services.ai_service import generate_content_draft


router = APIRouter()


@router.get("/calendar", response_model=list[ContentOut])
async def get_calendar(
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    conditions = [ContentCalendar.user_id == current_user.id]
    if start_date:
        conditions.append(ContentCalendar.scheduled_date >= start_date)
    if end_date:
        conditions.append(ContentCalendar.scheduled_date <= end_date)
    if status:
        conditions.append(ContentCalendar.status == status)

    rows = (
        await db.execute(
            select(ContentCalendar).where(and_(*conditions)).order_by(ContentCalendar.scheduled_date)
        )
    ).scalars().all()
    return [ContentOut.model_validate(c) for c in rows]


@router.post("/", response_model=ContentOut)
async def create_content(
    payload: ContentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ContentOut:
    item = ContentCalendar(user_id=current_user.id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ContentOut.model_validate(item)


@router.patch("/{content_id}", response_model=ContentOut)
async def update_content_item(
    content_id: str,
    payload: ContentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ContentOut:
    item = await db.get(ContentCalendar, content_id)
    if item is None or item.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Content item not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return ContentOut.model_validate(item)


@router.post("/generate-draft")
async def generate_draft(
    payload: ContentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = prof_res.scalar_one_or_none()
    profile_dict = {}
    if profile is not None:
        profile_dict = {
            "full_name": profile.full_name,
            "positioning_statement": profile.positioning_statement,
            "target_roles": profile.target_roles,
        }

    draft = await generate_content_draft(payload.topic, payload.category or "", profile_dict)
    if draft is None:
        raise HTTPException(status_code=503, detail="AI draft generation failed")

    item = ContentCalendar(
        user_id=current_user.id,
        scheduled_date=payload.scheduled_date,
        topic=payload.topic,
        category=payload.category,
        draft_text=draft,
        status="Drafted",
    )
    db.add(item)
    await db.commit()

    return {"id": str(item.id), "draft_text": draft}
