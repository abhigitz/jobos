import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import limiter
from app.dependencies import get_current_user
from app.models.profile import ProfileDNA
from app.schemas.profile import ProfileExtractRequest, ProfileOut, ProfileUpdate
from app.services.ai_service import call_claude, extract_profile
from app.utils.json_parser import parse_json_response


router = APIRouter()
logger = logging.getLogger(__name__)


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
@limiter.limit("50/hour")
async def extract_profile_from_resume(
    request: Request,
    payload: ProfileExtractRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Send resume text → Claude extracts structured profile → upsert profile_dna."""
    prompt = f"""Extract a structured professional profile from this resume.

CRITICAL RULES:
1. Extract EVERY bullet point from work experience as an achievement
2. Always include metrics when numbers/percentages/amounts appear in the bullet
3. Map each achievement to the company where it occurred
4. For achievements without explicit metrics, use "N/A" for the metric field

Return ONLY valid JSON:
{{
    "full_name": "Full Name from resume",
    "linkedin_url": "LinkedIn profile URL if present in resume, else null",
    "phone": "Phone number if present in resume, else null",
    "positioning_statement": "One sentence summary of their professional identity",
    "target_roles": ["Target role 1", "Target role 2"],
    "core_skills": ["skill1", "skill2", "skill3"],
    "tools_platforms": ["tool1", "tool2"],
    "industries": ["industry1", "industry2"],
    "achievements": [
        {{"company": "Company Name", "description": "Led cross-functional team to launch new product", "metric": "15% revenue increase"}},
        {{"company": "Company Name", "description": "Built data pipeline", "metric": "N/A"}}
    ],
    "resume_keywords": ["keyword1", "keyword2"],
    "education": [{{"institution": "University", "degree": "Degree", "year": "2020"}}],
    "alumni_networks": ["Network1", "Network2"],
    "career_narrative": "3-4 sentence career story",
    "experience_level": "Entry|Mid|Senior|Director|VP",
    "years_of_experience": 10
}}

RESUME TEXT:
{payload.resume_text}"""

    try:
        raw_result = await call_claude(prompt, max_tokens=4000)
        if raw_result is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI extraction failed")
        data = parse_json_response(raw_result)
        if data is None:
            # Fallback to existing extract_profile
            data = await extract_profile(payload.resume_text)
        if data is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI extraction failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Failed to extract profile from resume")

    result = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ProfileDNA(user_id=current_user.id)
        db.add(profile)

    profile.raw_resume_text = payload.resume_text

    for key, value in data.items():
        if hasattr(profile, key):
            setattr(profile, key, value)

    await db.commit()
    await db.refresh(profile)

    keywords = data.get("resume_keywords") or []
    return {"profile": ProfileOut.model_validate(profile), "keyword_count": len(keywords)}
