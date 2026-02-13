"""Scoring engine for job scouting — ranks jobs based on user preferences."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, List, Optional

from app.models.company import Company
from app.models.scout import ScoutedJob, UserScoutPreferences


@dataclass
class ScoreResult:
    """Result of scoring a job against user preferences."""

    total: int
    breakdown: dict[str, int]
    reasons: list[str]


# --- Helper functions ---


def normalize_for_matching(text: str | None) -> str:
    """Lowercase, remove punctuation, normalize whitespace."""
    if not text or not isinstance(text, str):
        return ""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_title_keywords(title: str | None) -> list[str]:
    """Split title into meaningful words (exclude very short/common words)."""
    if not title:
        return []
    normalized = normalize_for_matching(title)
    # Exclude stop words and very short tokens
    stop = {"a", "an", "the", "of", "at", "in", "on", "to", "for", "and", "or", "at"}
    words = [w for w in normalized.split() if len(w) >= 2 and w not in stop]
    return words


def check_keyword_overlap(text: str | None, keywords: list[str]) -> int:
    """Count how many keywords appear in text (case-insensitive)."""
    if not text or not keywords:
        return 0
    text_norm = normalize_for_matching(text)
    text_words = set(text_norm.split())
    count = 0
    for kw in keywords:
        kw_norm = normalize_for_matching(kw)
        if not kw_norm:
            continue
        # Check if keyword (or its parts) appears in text
        kw_parts = kw_norm.split()
        if all(part in text_words or part in text_norm for part in kw_parts):
            count += 1
    return count


def _parse_min_salary_from_range(salary_range: str | None) -> int | None:
    """Parse min salary in INR from strings like '90 LPA', '50-80 Lakh'."""
    if not salary_range or not isinstance(salary_range, str):
        return None
    s = salary_range.strip()
    # Match "X-Y Lakh" or "X-Y LPA"
    range_m = re.search(r"([\d.]+)\s*(?:-|to)\s*([\d.]+)\s*(?:lakh|lpa|lac)", s, re.IGNORECASE)
    if range_m:
        return int(float(range_m.group(1)) * 100_000)
    # Single value "X Lakh" or "X LPA"
    single_m = re.search(r"([\d.]+)\s*(?:lakh|lpa|lac)", s, re.IGNORECASE)
    if single_m:
        return int(float(single_m.group(1)) * 100_000)
    # Raw number
    num_m = re.search(r"(\d+)", s)
    if num_m:
        val = int(num_m.group(1))
        if val < 1000:  # Likely in lakhs
            return val * 100_000
        return val
    return None


def _get_company_id(job: ScoutedJob, company: Company | None) -> uuid.UUID | None:
    """Get company ID from job's matched_company_id or passed company."""
    if company:
        return company.id
    return job.matched_company_id if hasattr(job, "matched_company_id") else None


def _get_job_salary_min(job: ScoutedJob) -> int | None:
    """Get effective min salary from job (salary_min or salary_max for single-value)."""
    if hasattr(job, "salary_min") and job.salary_min is not None:
        return job.salary_min
    if hasattr(job, "salary_max") and job.salary_max is not None:
        return job.salary_max
    return None


def _get_job_posted_date(job: ScoutedJob) -> date | None:
    """Get posted date from job."""
    if hasattr(job, "posted_date") and job.posted_date is not None:
        return job.posted_date
    return None


def _days_ago(posted: date | None) -> int | None:
    """Days since posted date. None if no date."""
    if not posted:
        return None
    today = datetime.now(timezone.utc).date()
    return (today - posted).days


# --- Main scoring ---


def score_job(
    job: ScoutedJob,
    prefs: UserScoutPreferences,
    company: Company | None = None,
) -> ScoreResult:
    """
    Score a scouted job against user preferences (0-100 points).
    Returns ScoreResult with total, breakdown, and human-readable reasons.
    Hard filters (excluded company/industry) return score=0.
    """
    breakdown: dict[str, int] = {}
    reasons: list[str] = []

    company_id = _get_company_id(job, company)
    company_name = getattr(job, "company_name", None) or ""
    job_title = getattr(job, "title", None) or ""
    job_location = getattr(job, "location", None) or ""
    job_city = getattr(job, "city", None) or ""
    job_description = getattr(job, "description", None) or ""

    # --- Hard filters ---
    excluded_company_ids = list(prefs.excluded_company_ids or [])
    excluded_industries = [normalize_for_matching(i) for i in (prefs.excluded_industries or [])]

    if company_id and str(company_id) in [str(x) for x in excluded_company_ids]:
        return ScoreResult(total=0, breakdown={"hard_filter": 0}, reasons=["Company is excluded"])

    if excluded_industries and company:
        industry_norm = normalize_for_matching(company.sector or "")
        if industry_norm and any(ex in industry_norm or industry_norm in ex for ex in excluded_industries):
            return ScoreResult(total=0, breakdown={"hard_filter": 0}, reasons=["Industry is excluded"])

    # --- 1. Title match (0-40 pts) ---
    target_roles = [normalize_for_matching(r) for r in (prefs.target_roles or []) if r]
    role_keywords = [normalize_for_matching(k) for k in (prefs.role_keywords or []) if k]
    title_norm = normalize_for_matching(job_title)
    title_words = extract_title_keywords(job_title)

    title_pts = 0
    if target_roles and any(tr in title_norm for tr in target_roles):
        title_pts = 40
        reasons.append("Exact match with target role")
    else:
        all_keywords = role_keywords or [w for r in (prefs.target_roles or []) for w in r.split()]
        matches = sum(1 for k in all_keywords if k and k in title_norm)
        if matches >= 2:
            title_pts = 25
            reasons.append("2+ keyword matches in title")
        elif matches >= 1:
            title_pts = 15
            reasons.append("1 keyword match in title")
    breakdown["title"] = title_pts

    # --- 2. Company match (0-25 pts) ---
    company_pts = 0
    target_company_ids = list(prefs.target_company_ids or [])
    target_industries = [normalize_for_matching(i) for i in (prefs.target_industries or [])]
    company_stages = [normalize_for_matching(s) for s in (prefs.company_stages or [])]

    if company_id and str(company_id) in [str(x) for x in target_company_ids]:
        company_pts = 25
        reasons.append("Company in target list")
    elif company and target_industries:
        industry_norm = normalize_for_matching(company.sector or "")
        if industry_norm and any(ti in industry_norm or industry_norm in ti for ti in target_industries):
            company_pts = 15
            reasons.append("Industry matches target")
    elif company and company_stages:
        stage_norm = normalize_for_matching(company.stage or "")
        if stage_norm and any(cs in stage_norm or stage_norm in cs for cs in company_stages):
            company_pts = 10
            reasons.append("Company stage matches preferred")
    breakdown["company"] = company_pts

    # --- 3. Location match (0-15 pts) ---
    location_pts = 0
    target_locations = [normalize_for_matching(l) for l in (prefs.target_locations or []) if l]
    loc_norm = normalize_for_matching(job_location)
    city_norm = normalize_for_matching(job_city)

    if "remote" in loc_norm or "remote" in city_norm:
        location_pts = 15
        reasons.append("Remote role")
    elif target_locations:
        for tl in target_locations:
            if tl in loc_norm or tl in city_norm or (city_norm and tl in city_norm):
                location_pts = 15
                reasons.append("City matches target location")
                break

    # Location penalty
    location_flexibility = (prefs.location_flexibility or "preferred").lower()
    if location_flexibility == "strict" and location_pts == 0 and target_locations:
        location_pts = -20
        reasons.append("Location mismatch (strict mode)")
    breakdown["location"] = location_pts

    # --- 4. Salary match (0-10 pts) ---
    salary_pts = 0
    min_salary = prefs.min_salary
    job_sal = _get_job_salary_min(job)
    salary_flexibility = (prefs.salary_flexibility or "flexible").lower()

    if min_salary and job_sal is not None:
        if job_sal >= min_salary:
            salary_pts = 10
            reasons.append("Meets minimum salary")
        elif job_sal >= int(min_salary * 0.85):
            salary_pts = 5
            reasons.append("Within 85% of minimum salary")
        elif salary_flexibility == "strict":
            salary_pts = -15
            reasons.append("Below minimum (strict mode)")
    breakdown["salary"] = salary_pts

    # --- 5. Keyword match (0-5 pts) ---
    kw_pts = 0
    role_keywords_prefs = list(prefs.role_keywords or [])
    if role_keywords_prefs and job_description:
        count = check_keyword_overlap(job_description, role_keywords_prefs)
        kw_pts = min(count, 5)
        if kw_pts > 0:
            reasons.append(f"{kw_pts} role keywords in description")
    breakdown["keywords"] = kw_pts

    # --- 6. Recency bonus (0-5 pts) ---
    recency_pts = 0
    days = _days_ago(_get_job_posted_date(job))
    if days is not None:
        if days <= 1:
            recency_pts = 5
            reasons.append("Posted ≤1 day ago")
        elif days <= 3:
            recency_pts = 3
            reasons.append("Posted ≤3 days ago")
        elif days <= 7:
            recency_pts = 1
            reasons.append("Posted ≤7 days ago")
    breakdown["recency"] = recency_pts

    # --- 7. Learned adjustments ---
    learned_pts = 0
    boosts = prefs.learned_boosts or {}
    penalties = prefs.learned_penalties or {}

    def _apply_learned(d: dict[str, Any], multiplier: int) -> int:
        total = 0
        # Structure: {"companies": {uuid: pts} or [uuid], "company_ids": [uuid], "title_words": {word: pts}}
        for key, val in d.items():
            if isinstance(val, dict):
                if key == "companies" and company_id:
                    pid = str(company_id)
                    if pid in val and isinstance(val[pid], (int, float)):
                        total += val[pid]
                    elif any(str(k) == pid for k in val.keys()):
                        for k, v in val.items():
                            if str(k) == pid and isinstance(v, (int, float)):
                                total += v
                                break
                elif key == "company_names" and company_name:
                    cn_norm = normalize_for_matching(company_name)
                    for k, v in val.items():
                        if isinstance(v, (int, float)) and normalize_for_matching(str(k)) == cn_norm:
                            total += v
                            break
                elif key == "title_words" and job_title:
                    title_norm = normalize_for_matching(job_title)
                    for word, v in val.items():
                        if isinstance(v, (int, float)) and str(word) in title_norm:
                            total += v
            elif isinstance(val, list) and key in ("companies", "company_ids") and company_id:
                if str(company_id) in [str(x) for x in val]:
                    total += 10 * multiplier  # default penalty when in list
            elif isinstance(val, (int, float)):
                total += val
        return total * multiplier

    learned_pts = _apply_learned(boosts, 1) - _apply_learned(penalties, 1)
    if learned_pts != 0:
        reasons.append(f"Learned adjustment: {'+' if learned_pts > 0 else ''}{learned_pts}")
    breakdown["learned"] = learned_pts

    # --- Total ---
    total = sum(breakdown.values())
    total = max(0, min(100, total))

    return ScoreResult(total=total, breakdown=breakdown, reasons=reasons)
