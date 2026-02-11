import json
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.profile import ProfileDNA
from app.schemas.profile import ProfileExtractRequest, ProfileOut, ProfileUpdate
from app.services.ai_service import call_claude, extract_profile


router = APIRouter()


def _extract_json(text: str) -> dict:
    """Extract JSON from Claude response, handling markdown code blocks."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if match:
        return json.loads(match.group(1))
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        return json.loads(text[start:end + 1])
    raise ValueError("Could not extract JSON from AI response")


@router.get("", response_model=ProfileOut)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProfileOut:
    result = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return ProfileOut.model_validate(profile)


@router.put("", response_model=ProfileOut)
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


@router.patch("", response_model=ProfileOut)
async def patch_profile(
    payload: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ProfileOut:
    """Update individual profile fields (PATCH semantics)."""
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
    """Send resume text → Claude extracts structured profile → upsert profile_dna."""
    prompt = f"""Extract structured profile data from this resume. Return ONLY valid JSON.

{{
    "full_name": "...",
    "positioning_statement": "one sentence summary",
    "target_roles": ["role1", "role2"],
    "core_skills": ["skill1", "skill2"],
    "tools_platforms": ["tool1"],
    "industries": ["industry1"],
    "achievements": [{{"description": "...", "metric": "...", "company": "..."}}],
    "resume_keywords": ["keyword1", "keyword2"],
    "education": [{{"institution": "...", "degree": "...", "year": "..."}}],
    "alumni_networks": ["IIT Delhi", "IIM Calcutta"],
    "career_narrative": "3-4 sentence career story",
    "experience_level": "Entry|Mid|Senior|Director|VP",
    "years_of_experience": 13
}}

RESUME TEXT:
{payload.resume_text}"""

    try:
        raw_result = await call_claude(prompt, max_tokens=2000)
        if raw_result is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI extraction failed")
        data = _extract_json(raw_result)
    except (json.JSONDecodeError, ValueError):
        # Fallback to existing extract_profile
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
