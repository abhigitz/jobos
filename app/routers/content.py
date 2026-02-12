import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, limiter
from app.models.content import ContentCalendar
from app.models.profile import ProfileDNA
from app.schemas.content import ContentCreate, ContentOut, ContentUpdate
from app.services.ai_service import call_claude, generate_content_draft, parse_json_response
from app.services.activity_log import log_activity


router = APIRouter()

VALID_STATUSES = {"Planned", "Drafted", "Reviewed", "Published"}


class GenerateBatchRequest(BaseModel):
    days: int = Field(7, ge=1, le=30)


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


@router.post("/calendar", response_model=ContentOut)
async def add_custom_topic(
    payload: ContentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ContentOut:
    """Add a custom topic. Dedup: check if topic already exists for this date."""
    existing = await db.execute(
        select(ContentCalendar).where(
            ContentCalendar.user_id == current_user.id,
            ContentCalendar.scheduled_date == payload.scheduled_date,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A topic already exists for this date")

    item = ContentCalendar(user_id=current_user.id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ContentOut.model_validate(item)


@router.patch("/calendar/{content_id}", response_model=ContentOut)
async def update_calendar_item(
    content_id: str,
    payload: ContentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ContentOut:
    """Edit draft text, change status, log engagement."""
    item = await db.get(ContentCalendar, content_id)
    if item is None or item.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Content item not found")

    if payload.status and payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(VALID_STATUSES)}")

    old_status = item.status
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)

    if payload.status == "Published" and old_status != "Published":
        await log_activity(
            db, current_user.id, "content_published",
            f"Published content: {item.topic}",
        )
        await db.commit()

    return ContentOut.model_validate(item)


@router.delete("/calendar/{content_id}")
async def delete_calendar_item(
    content_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Remove a topic. Only if status is 'Planned' or 'Drafted'. Can't delete Published posts."""
    item = await db.get(ContentCalendar, content_id)
    if item is None or item.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Content item not found")

    if item.status in ("Published", "Reviewed"):
        raise HTTPException(status_code=400, detail=f"Cannot delete content with status '{item.status}'")

    await db.delete(item)
    await db.commit()
    return {"status": "deleted"}


@router.post("/generate-batch")
@limiter.limit("50/hour")
async def generate_batch(
    request: Request,
    payload: GenerateBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate topics for the next N days that don't have topics yet."""
    today = date.today()

    # Find dates that already have entries
    existing_entries = (
        await db.execute(
            select(ContentCalendar.scheduled_date).where(
                ContentCalendar.user_id == current_user.id,
                ContentCalendar.scheduled_date >= today,
            )
        )
    ).scalars().all()
    existing_dates = set(existing_entries)

    # Find the next N dates without entries
    dates_needed = []
    check_date = today
    while len(dates_needed) < payload.days:
        if check_date not in existing_dates:
            dates_needed.append(check_date)
        check_date += timedelta(days=1)

    if not dates_needed:
        return {"generated": 0, "dates": []}

    # Get profile for context
    prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = prof_res.scalar_one_or_none()
    profile_dict = {}
    if profile:
        profile_dict = {
            "full_name": profile.full_name,
            "positioning_statement": profile.positioning_statement,
            "target_roles": profile.target_roles,
        }

    dates_str = ", ".join(d.isoformat() for d in dates_needed)
    prompt = f"""Generate {len(dates_needed)} LinkedIn post topics for a growth leader in consumer tech.

PROFILE CONTEXT: {json.dumps(profile_dict, default=str)}

Mix: 2x Growth/Marketing insights, 1x GenAI in marketing, 1x Strategy/Ops, 1x Industry analysis, 1x Personal/Career, 1x Leadership

For each, provide topic title and category.

DATES TO FILL: {dates_str}

Return ONLY valid JSON array:
[{{"date": "2026-03-01", "topic": "...", "category": "..."}}]"""

    try:
        result = await call_claude(prompt, max_tokens=1000)
        data = parse_json_response(result)
    except Exception:
        raise HTTPException(status_code=503, detail="AI generation failed")

    if data is None:
        raise HTTPException(status_code=503, detail="AI generation returned invalid data")

    # Handle both list and dict with "topics" key
    topics = data if isinstance(data, list) else data.get("topics", [])

    created_dates = []
    for i, topic_data in enumerate(topics):
        if i >= len(dates_needed):
            break
        topic_date = dates_needed[i]
        item = ContentCalendar(
            user_id=current_user.id,
            scheduled_date=topic_date,
            topic=topic_data.get("topic", ""),
            category=topic_data.get("category", ""),
            status="Planned",
        )
        db.add(item)
        created_dates.append(topic_date.isoformat())

    await db.commit()

    return {"generated": len(created_dates), "dates": created_dates}


@router.post("/initialize")
async def initialize_content_calendar(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate starter content topics for new users."""
    existing = await db.execute(
        select(ContentCalendar).where(ContentCalendar.user_id == current_user.id).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Content calendar already initialized")

    prof_res = await db.execute(
        select(ProfileDNA).where(ProfileDNA.user_id == current_user.id)
    )
    profile = prof_res.scalar_one_or_none()

    default_topics = [
        {"topic": "Career transition lessons learned", "category": "Personal"},
        {"topic": "Industry trend I'm excited about", "category": "Industry"},
        {"topic": "Skill I'm currently developing", "category": "Growth"},
        {"topic": "Professional win worth sharing", "category": "Personal"},
        {"topic": "Advice for others in similar roles", "category": "Strategy"},
    ]

    base_date = date.today()
    for i, item in enumerate(default_topics):
        content = ContentCalendar(
            user_id=current_user.id,
            topic=item["topic"],
            category=item["category"],
            scheduled_date=base_date + timedelta(days=i * 2),
            status="Planned",
        )
        db.add(content)

    await db.commit()
    return {"message": "Content calendar initialized with 5 starter topics", "count": 5}


@router.post("/initialize")
async def initialize_content_calendar(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Generate starter content topics for new users."""
    existing = await db.execute(
        select(ContentCalendar).where(ContentCalendar.user_id == current_user.id).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Content calendar already initialized")

    prof_res = await db.execute(
        select(ProfileDNA).where(ProfileDNA.user_id == current_user.id)
    )
    profile = prof_res.scalar_one_or_none()

    default_topics = [
        {"topic": "Career transition lessons learned", "category": "Personal"},
        {"topic": "Industry trend I'm excited about", "category": "Industry"},
        {"topic": "Skill I'm currently developing", "category": "Growth"},
        {"topic": "Professional win worth sharing", "category": "Personal"},
        {"topic": "Advice for others in similar roles", "category": "Strategy"},
    ]

    base_date = date.today()
    for i, item in enumerate(default_topics):
        content = ContentCalendar(
            user_id=current_user.id,
            topic=item["topic"],
            category=item["category"],
            scheduled_date=base_date + timedelta(days=i * 2),
            status="Planned",
        )
        db.add(content)

    await db.commit()
    return {"message": "Content calendar initialized with 5 starter topics", "count": 5}


# --- Existing endpoints preserved ---

@router.post("", response_model=ContentOut)
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


@router.post("/{content_id}/shuffle")
@limiter.limit("50/hour")
async def shuffle_content(
    request: Request,
    content_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Regenerate a single content piece while keeping others."""
    content = await db.get(ContentCalendar, content_id)
    if not content or content.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Content not found")

    prof_res = await db.execute(
        select(ProfileDNA).where(ProfileDNA.user_id == current_user.id)
    )
    profile = prof_res.scalar_one_or_none()

    from app.services.ai_service import generate_single_post
    new_post = await generate_single_post(
        topic=content.topic,
        content_type=content.category or "",
        profile=profile,
    )

    if new_post is None:
        raise HTTPException(status_code=503, detail="AI generation failed")

    content.draft_text = new_post
    content.status = "Drafted"
    content.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(content)

    return ContentOut.model_validate(content)


@router.patch("/{content_id}/draft")
async def save_draft(
    content_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Save edited draft content."""
    content = await db.get(ContentCalendar, content_id)
    if not content or content.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Content not found")

    content.draft_text = payload.get("draft_text", content.draft_text)
    content.status = "Drafted"
    content.updated_at = datetime.utcnow()
    await db.commit()

    return {"message": "Draft saved"}


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
@limiter.limit("50/hour")
async def generate_draft(
    request: Request,
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
