"""Service for managing user scout preferences with auto-population from profile_dna."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import ProfileDNA
from app.models.scout import ScoutedJob, UserScoutPreferences, UserScoutedJob

# Default excluded industries (e.g. vegetarian filter)
DEFAULT_EXCLUDED_INDUSTRIES = ["Food Delivery"]


def _parse_min_salary_from_range(salary_range: Optional[str]) -> Optional[int]:
    """Parse min salary in INR from strings like '90 LPA', '50-80 Lakh'."""
    if not salary_range or not isinstance(salary_range, str):
        return None
    s = salary_range.strip()
    range_m = re.search(
        r"([\d.]+)\s*(?:-|to)\s*([\d.]+)\s*(?:lakh|lpa|lac)",
        s,
        re.IGNORECASE,
    )
    if range_m:
        return int(float(range_m.group(1)) * 100_000)
    single_m = re.search(
        r"([\d.]+)\s*(?:lakh|lpa|lac)",
        s,
        re.IGNORECASE,
    )
    if single_m:
        return int(float(single_m.group(1)) * 100_000)
    num_m = re.search(r"(\d+)", s)
    if num_m:
        val = int(num_m.group(1))
        if val < 1000:
            return val * 100_000
        return val
    return None


def _extract_title_words(title: Optional[str]) -> list[str]:
    """Extract meaningful words from job title for penalty learning."""
    if not title:
        return []
    s = title.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    words = [w for w in s.split() if len(w) >= 3]
    return words[:5]  # Limit to 5 most common


async def get_or_create_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> UserScoutPreferences:
    """
    Get user scout preferences. If none exist, create from profile_dna.
    """
    result = await db.execute(
        select(UserScoutPreferences).where(UserScoutPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is not None:
        return prefs

    # Create from profile_dna
    prof_result = await db.execute(
        select(ProfileDNA).where(ProfileDNA.user_id == user_id)
    )
    profile = prof_result.scalar_one_or_none()

    target_roles: List[str] = []
    target_locations: List[str] = []
    min_salary: Optional[int] = None
    role_keywords: List[str] = []
    target_industries: List[str] = []

    if profile:
        target_roles = list(profile.target_roles or [])
        target_locations = list(profile.target_locations or [])
        min_salary = _parse_min_salary_from_range(profile.target_salary_range)
        role_keywords = list(profile.core_skills or []) + list(profile.resume_keywords or [])
        role_keywords = list(dict.fromkeys(role_keywords))  # dedupe
        target_industries = list(profile.industries or [])

    prefs = UserScoutPreferences(
        user_id=user_id,
        target_roles=target_roles,
        role_keywords=role_keywords,
        target_locations=target_locations,
        min_salary=min_salary,
        target_industries=target_industries,
        excluded_industries=DEFAULT_EXCLUDED_INDUSTRIES,
    )
    db.add(prefs)
    await db.commit()
    await db.refresh(prefs)
    return prefs


async def sync_preferences_from_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> Optional[UserScoutPreferences]:
    """
    Update existing preferences with latest profile_dna values.
    Updates synced_from_profile_at timestamp.
    Returns None if no preferences exist.
    """
    result = await db.execute(
        select(UserScoutPreferences).where(UserScoutPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        return None

    prof_result = await db.execute(
        select(ProfileDNA).where(ProfileDNA.user_id == user_id)
    )
    profile = prof_result.scalar_one_or_none()

    if profile:
        prefs.target_roles = list(profile.target_roles or [])
        prefs.target_locations = list(profile.target_locations or [])
        prefs.min_salary = _parse_min_salary_from_range(profile.target_salary_range)
        prefs.role_keywords = list(profile.core_skills or []) + list(profile.resume_keywords or [])
        prefs.role_keywords = list(dict.fromkeys(prefs.role_keywords))
        prefs.target_industries = list(profile.industries or [])

    prefs.synced_from_profile_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(prefs)
    return prefs


async def update_learned_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    dismiss_reason: str,
    job: ScoutedJob,
) -> None:
    """
    Apply learning rules based on dismiss feedback.
    - wrong_company → add to learned_penalties
    - salary_low (3+ times) → raise min_salary 10%
    - wrong_location (3+ times) → set location_flexibility to "strict"
    - wrong_role → penalize common title words
    """
    result = await db.execute(
        select(UserScoutPreferences).where(UserScoutPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        return

    reason = (dismiss_reason or "").strip().lower()

    if reason == "wrong_company":
        # Add company to learned_penalties
        company_id = job.matched_company_id if hasattr(job, "matched_company_id") else None
        if company_id:
            penalties = dict(prefs.learned_penalties or {})
            companies = dict(penalties.get("companies", {}))
            companies[str(company_id)] = companies.get(str(company_id), 0) - 15
            penalties["companies"] = companies
            prefs.learned_penalties = penalties
        else:
            # Fallback: use company name
            company_name = getattr(job, "company_name", None)
            if company_name:
                penalties = dict(prefs.learned_penalties or {})
                names = dict(penalties.get("company_names", {}))
                names[company_name] = names.get(company_name, 0) - 15
                penalties["company_names"] = names
                prefs.learned_penalties = penalties

    elif reason == "salary_low":
        # Count dismissals for salary_low (trigger on 3rd dismissal)
        count_result = await db.execute(
            select(UserScoutedJob).where(
                UserScoutedJob.user_id == user_id,
                UserScoutedJob.dismiss_reason == "salary_low",
            )
        )
        count = len(count_result.scalars().all())
        if count >= 3 and prefs.min_salary:
            prefs.min_salary = int(prefs.min_salary * 1.1)

    elif reason == "wrong_location":
        # Count dismissals for wrong_location (trigger on 3rd dismissal)
        count_result = await db.execute(
            select(UserScoutedJob).where(
                UserScoutedJob.user_id == user_id,
                UserScoutedJob.dismiss_reason == "wrong_location",
            )
        )
        count = len(count_result.scalars().all())
        if count >= 3:
            prefs.location_flexibility = "strict"

    elif reason == "wrong_role":
        # Penalize common title words
        title = getattr(job, "title", None)
        words = _extract_title_words(title)
        if words:
            penalties = dict(prefs.learned_penalties or {})
            title_words = dict(penalties.get("title_words", {}))
            for w in words:
                title_words[w] = title_words.get(w, 0) - 5
            penalties["title_words"] = title_words
            prefs.learned_penalties = penalties

    await db.commit()
