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

# Company key -> Greenhouse board ID
GREENHOUSE_COMPANIES: dict[str, str] = {
    "phonepe": "phonepe",
    "razorpay": "razorpaysoftwareprivatelimited",
    "flipkart": "flipkart",
    "myntra": "myntra",
    "groww": "groww",
    "zerodha": "zerodha",
    "curefit": "caborneoadvisors",  # Cult.fit parent company
    "urban_company": "urbancompany",
    "lenskart": "laborx",  # Lenskart's Greenhouse board
    "nykaa": "nykaa",
}

# Company key -> Lever posting ID
LEVER_COMPANIES: dict[str, str] = {
    "cred": "cred",
    "meesho": "meesho",
    "zepto": "zepto",
    "jupiter": "jupiter-money",
    "slice": "slicepay",
    "khatabook": "khatabook",
    "unacademy": "unacademy",
    "sharechat": "sharechatapp",
}

# Slug -> display name for special cases
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


async def fetch_greenhouse_jobs() -> list[dict[str, Any]]:
    """
    Fetch jobs from all Greenhouse companies.
    URL: https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs
    Returns normalized job dicts with: title, location, url, company_name, source="greenhouse"
    """
    all_jobs: list[dict[str, Any]] = []

    for company_name, board_id in GREENHOUSE_COMPANIES.items():
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs"
        display_name = COMPANY_SLUG_TO_NAME.get(company_name.lower(), company_name.replace("_", " ").title())

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)

            if resp.status_code != 200:
                logger.warning(f"Greenhouse {company_name} ({board_id}): HTTP {resp.status_code}")
                continue

            data = resp.json()
            raw_jobs = data.get("jobs") if isinstance(data, dict) else []

            if not isinstance(raw_jobs, list):
                continue

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

                company_norm = normalize_company(display_name)
                city = extract_city(location) if location else None
                dedup_hash = generate_dedup_hash(display_name, title, location or "")

                all_jobs.append({
                    "external_id": str(raw.get("id", "")),
                    "dedup_hash": dedup_hash,
                    "title": title,
                    "company_name": display_name,
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
            logger.warning(f"Greenhouse {company_name} ({board_id}): HTTP error: {e}")
        except Exception as e:
            logger.warning(f"Greenhouse {company_name} ({board_id}): error: {e}")

    return all_jobs


async def fetch_lever_jobs() -> list[dict[str, Any]]:
    """
    Fetch jobs from all Lever companies.
    URL: https://api.lever.co/v0/postings/{lever_id}?mode=json
    Returns normalized job dicts with: title, location, url, company_name, source="lever"
    """
    all_jobs: list[dict[str, Any]] = []

    for company_name, lever_id in LEVER_COMPANIES.items():
        url = f"https://api.lever.co/v0/postings/{lever_id}?mode=json"
        display_name = COMPANY_SLUG_TO_NAME.get(company_name.lower(), company_name.replace("_", " ").title())

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)

            if resp.status_code != 200:
                logger.warning(f"Lever {company_name} ({lever_id}): HTTP {resp.status_code}")
                continue

            data = resp.json()
            if not isinstance(data, list):
                continue

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

                company_norm = normalize_company(display_name)
                city = extract_city(location) if location else None
                dedup_hash = generate_dedup_hash(display_name, title, location or "")

                all_jobs.append({
                    "external_id": str(raw.get("id", "")),
                    "dedup_hash": dedup_hash,
                    "title": title,
                    "company_name": display_name,
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
            logger.warning(f"Lever {company_name} ({lever_id}): HTTP error: {e}")
        except Exception as e:
            logger.warning(f"Lever {company_name} ({lever_id}): error: {e}")

    return all_jobs


async def fetch_target_company_jobs() -> list[dict[str, Any]]:
    """
    Fetch jobs from target companies: Greenhouse and Lever.
    Combines all results. Handles errors gracefully (if one fails, continue with others).
    """
    all_jobs: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    # Greenhouse companies
    try:
        jobs = await fetch_greenhouse_jobs()
        for job in jobs:
            h = job.get("dedup_hash")
            if h and h not in seen_hashes:
                seen_hashes.add(h)
                all_jobs.append(job)
    except Exception as e:
        logger.warning(f"fetch_target_company_jobs: Greenhouse failed: {e}")

    # Lever companies
    try:
        jobs = await fetch_lever_jobs()
        for job in jobs:
            h = job.get("dedup_hash")
            if h and h not in seen_hashes:
                seen_hashes.add(h)
                all_jobs.append(job)
    except Exception as e:
        logger.warning(f"fetch_target_company_jobs: Lever failed: {e}")

    return all_jobs
