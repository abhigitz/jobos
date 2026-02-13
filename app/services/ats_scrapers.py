"""ATS scrapers for Greenhouse and Lever job boards."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.services.serpapi_service import (
    extract_city,
    generate_dedup_hash,
    normalize_company,
)

logger = logging.getLogger(__name__)

# Slug -> display name for target companies
COMPANY_SLUG_TO_NAME: dict[str, str] = {
    "phonepe": "PhonePe",
    "razorpaysoftwareprivatelimited": "Razorpay",
    "cred": "CRED",
    "meesho": "Meesho",
}


def _company_name_from_slug(slug: str) -> str:
    """Get display company name from slug; fallback to title-cased slug."""
    return COMPANY_SLUG_TO_NAME.get(slug.lower(), slug.replace("-", " ").title())


def _strip_html(html: str | None) -> str | None:
    """Strip HTML tags from content; return None if empty."""
    if not html or not html.strip():
        return None
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    return text if text else None


async def fetch_greenhouse_jobs(company_slug: str) -> list[dict[str, Any]]:
    """
    Fetch jobs from Greenhouse job board.
    URL: https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs
    Returns normalized job dicts with: title, location, url, company_name, source="greenhouse"
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
    jobs: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            logger.warning(f"Greenhouse {company_slug}: HTTP {resp.status_code}")
            return []

        data = resp.json()
        raw_jobs = data.get("jobs") if isinstance(data, dict) else []

        if not isinstance(raw_jobs, list):
            return []

        company_name = _company_name_from_slug(company_slug)
        now = datetime.now(timezone.utc)

        for raw in raw_jobs:
            if not isinstance(raw, dict):
                continue
            title = raw.get("title") or ""
            if not title:
                continue

            loc_obj = raw.get("location")
            location = loc_obj.get("name", "") if isinstance(loc_obj, dict) else (loc_obj or "")
            if isinstance(location, str):
                location = location.strip() or None
            else:
                location = str(location) if location else None

            url_val = raw.get("absolute_url") or ""
            if not url_val:
                continue

            content = raw.get("content")
            description = _strip_html(content) if content else None

            company_norm = normalize_company(company_name)
            city = extract_city(location) if location else None
            dedup_hash = generate_dedup_hash(company_name, title, location or "")

            jobs.append({
                "external_id": str(raw.get("id", "")),
                "dedup_hash": dedup_hash,
                "title": title,
                "company_name": company_name,
                "company_name_normalized": company_norm,
                "location": location,
                "city": city,
                "description": description,
                "salary_min": None,
                "salary_max": None,
                "salary_is_estimated": False,
                "source": "greenhouse",
                "source_url": url_val,
                "apply_url": url_val,
                "posted_date": None,
                "scouted_at": now,
                "last_seen_at": now,
                "raw_json": raw,
                "search_query": None,
            })

    except httpx.HTTPError as e:
        logger.warning(f"Greenhouse {company_slug}: HTTP error: {e}")
    except Exception as e:
        logger.warning(f"Greenhouse {company_slug}: error: {e}")

    return jobs


async def fetch_lever_jobs(company_slug: str) -> list[dict[str, Any]]:
    """
    Fetch jobs from Lever postings API.
    URL: https://api.lever.co/v0/postings/{company_slug}?mode=json
    Returns normalized job dicts with: title, location, url, company_name, source="lever"
    """
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    jobs: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            logger.warning(f"Lever {company_slug}: HTTP {resp.status_code}")
            return []

        data = resp.json()
        if not isinstance(data, list):
            return []

        company_name = _company_name_from_slug(company_slug)
        now = datetime.now(timezone.utc)

        for raw in data:
            if not isinstance(raw, dict):
                continue
            title = raw.get("text") or raw.get("title") or ""
            if not title:
                continue

            categories = raw.get("categories") or {}
            if isinstance(categories, dict):
                location = categories.get("location") or ""
                all_locs = categories.get("allLocations") or []
                if not location and all_locs:
                    location = ", ".join(all_locs) if isinstance(all_locs[0], str) else str(all_locs[0])
            else:
                location = ""

            location = location.strip() or None if location else None

            url_val = raw.get("hostedUrl") or raw.get("url") or ""
            if not url_val:
                continue

            company_norm = normalize_company(company_name)
            city = extract_city(location) if location else None
            dedup_hash = generate_dedup_hash(company_name, title, location or "")

            jobs.append({
                "external_id": str(raw.get("id", "")),
                "dedup_hash": dedup_hash,
                "title": title,
                "company_name": company_name,
                "company_name_normalized": company_norm,
                "location": location,
                "city": city,
                "description": raw.get("descriptionPlain") or raw.get("description") or None,
                "salary_min": None,
                "salary_max": None,
                "salary_is_estimated": False,
                "source": "lever",
                "source_url": url_val,
                "apply_url": raw.get("applyUrl") or url_val,
                "posted_date": None,
                "scouted_at": now,
                "last_seen_at": now,
                "raw_json": raw,
                "search_query": None,
            })

    except httpx.HTTPError as e:
        logger.warning(f"Lever {company_slug}: HTTP error: {e}")
    except Exception as e:
        logger.warning(f"Lever {company_slug}: error: {e}")

    return jobs


async def fetch_target_company_jobs() -> list[dict[str, Any]]:
    """
    Fetch jobs from target companies: Greenhouse (phonepe, razorpay) and Lever (cred, meesho).
    Combines all results. Handles errors gracefully (if one fails, continue with others).
    """
    all_jobs: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    # Greenhouse companies
    greenhouse_slugs = ["phonepe", "razorpaysoftwareprivatelimited"]
    for slug in greenhouse_slugs:
        try:
            jobs = await fetch_greenhouse_jobs(slug)
            for job in jobs:
                h = job.get("dedup_hash")
                if h and h not in seen_hashes:
                    seen_hashes.add(h)
                    all_jobs.append(job)
        except Exception as e:
            logger.warning(f"fetch_target_company_jobs: Greenhouse {slug} failed: {e}")

    # Lever companies
    lever_slugs = ["cred", "meesho"]
    for slug in lever_slugs:
        try:
            jobs = await fetch_lever_jobs(slug)
            for job in jobs:
                h = job.get("dedup_hash")
                if h and h not in seen_hashes:
                    seen_hashes.add(h)
                    all_jobs.append(job)
        except Exception as e:
            logger.warning(f"fetch_target_company_jobs: Lever {slug} failed: {e}")

    return all_jobs
