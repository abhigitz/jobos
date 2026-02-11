from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.profile import ProfileDNA
from app.schemas.profile import ProfileExtractRequest, ProfileOut, ProfileUpdate
from app.services.ai_service import extract_profile


router = APIRouter()


@router.get("/", response_model=ProfileOut)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProfileOut:
    result = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return ProfileOut.model_validate(profile)


@router.put("/", response_model=ProfileOut)
async def update_profile(
    payload: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProfileOut:
    result = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ProfileDNA(user_id=current_user.id)
        db.add(profile)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.post("/extract", response_model=dict)
async def extract_profile_from_resume(
    payload: ProfileExtractRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    data = await extract_profile(payload.resume_text)
    if data is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI extraction failed")

    result = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ProfileDNA(user_id=current_user.id)
        db.add(profile)

    for key, value in data.items():
        if hasattr(profile, key):
            setattr(profile, key, value)

    await db.commit()
    await db.refresh(profile)

    keywords = data.get("resume_keywords") or []
    return {"profile": ProfileOut.model_validate(profile), "keyword_count": len(keywords)}
