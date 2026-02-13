"""SerpAPI client service for job scouting via Google Jobs engine."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import get_settings

# Default search templates for job scouting
DEFAULT_SEARCH_TEMPLATES = [
    "VP Growth {location}",
    "Head of Growth {location}",
    "Director Growth {location}",
    "VP Marketing {location}",
    "Head of Marketing {location}",
    "Director Performance Marketing {location}",
    "Chief of Staff {location}",
    "Head of Strategy {location}",
    "Business Head {location}",
    "P&L Head {location}",
]

DEFAULT_LOCATIONS = ["Bangalore", "India"]

# Company name suffixes to strip for normalization
COMPANY_STRIP_PATTERNS = [
    r"\s+india\b",
    r"\s+pvt\.?\s*ltd\.?",
    r"\s+private\s+limited",
    r"\s+technologies\b",
    r"\s+tech\b",
    r"\s+limited\b",
    r"\s+ltd\.?",
    r"\s+inc\.?",
    r"\s+llc\b",
    r"\s+corp\.?",
]

# Title abbreviations for normalization
TITLE_ABBREVS = {
    "vice president": "vp",
    "senior": "sr",
    "assistant": "asst",
    "associate": "assoc",
    "director": "dir",
    "manager": "mgr",
    "chief": "chief",  # keep as-is
    "head": "head",   # keep as-is
}


def normalize_company(name: str) -> str:
    """Lowercase and remove common suffixes (India, Pvt Ltd, Technologies, etc.)."""
    if not name or not isinstance(name, str):
        return ""
    s = name.lower().strip()
    for pat in COMPANY_STRIP_PATTERNS:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def normalize_title(title: str) -> str:
    """Lowercase and abbreviate common terms (Vice President → vp, Senior → sr)."""
    if not title or not isinstance(title, str):
        return ""
    s = title.lower().strip()
    for full, abbr in TITLE_ABBREVS.items():
        s = re.sub(rf"\b{re.escape(full)}\b", abbr, s)
    return re.sub(r"\s+", " ", s).strip()


def extract_city(location: str) -> str | None:
    """Get first part before comma from location string."""
    if not location or not isinstance(location, str):
        return None
    parts = [p.strip() for p in location.split(",")]
    return parts[0] if parts else None


def generate_dedup_hash(company: str, title: str, location: str) -> str:
    """SHA256 hash of normalized 'company|title|city' for deduplication."""
    cn = normalize_company(company)
    tn = normalize_title(title)
    city = extract_city(location) or ""
    city = city.lower().strip()
    payload = f"{cn}|{tn}|{city}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_posted_date(date_str: str) -> datetime | None:
    """Convert relative date strings like '2 days ago', '1 week ago' to datetime."""
    if not date_str or not isinstance(date_str, str):
        return None
    s = date_str.lower().strip()
    now = datetime.now(timezone.utc)

    # "X days ago"
    m = re.search(r"(\d+)\s*days?\s*ago", s)
    if m:
        return now - timedelta(days=int(m.group(1)))

    # "X weeks ago"
    m = re.search(r"(\d+)\s*weeks?\s*ago", s)
    if m:
        return now - timedelta(weeks=int(m.group(1)))

    # "X months ago"
    m = re.search(r"(\d+)\s*months?\s*ago", s)
    if m:
        return now - timedelta(days=int(m.group(1)) * 30)

    # "yesterday"
    if "yesterday" in s:
        return now - timedelta(days=1)

    # "today"
    if "today" in s or "just posted" in s:
        return now

    # "last week", "last month"
    if "last week" in s:
        return now - timedelta(weeks=1)
    if "last month" in s:
        return now - timedelta(days=30)

    return None


def parse_salary(salary_str: str) -> tuple[int | None, int | None, bool]:
    """
    Extract min/max salary in INR from string. Returns (min, max, is_estimated).
    Detects 'estimated', 'approx', '~' etc. for is_estimated.
    """
    if not salary_str or not isinstance(salary_str, str):
        return None, None, False

    s = salary_str.strip()
    is_estimated = bool(
        re.search(r"estimated|approx\.?|approximately|~|up to", s, re.IGNORECASE)
    )

    # INR patterns: ₹X-Y Lakh, Rs X-Y Lakh, X-Y LPA, X-Y Lakh per annum, etc.
    # Also handle: X-Y Lakh, X Lakh - Y Lakh
    min_val = None
    max_val = None

    # Match "X - Y Lakh" or "X-Y Lakh" or "X Lakh - Y Lakh"
    lakh_match = re.search(
        r"(?:₹|Rs\.?|INR)?\s*([\d.]+)\s*(?:-|to)\s*([\d.]+)\s*(?:lakh|lpa|lac)",
        s,
        re.IGNORECASE,
    )
    if lakh_match:
        min_val = int(float(lakh_match.group(1)) * 100_000)
        max_val = int(float(lakh_match.group(2)) * 100_000)
        return min_val, max_val, is_estimated

    # Single value: "X Lakh"
    single_match = re.search(
        r"(?:₹|Rs\.?|INR)?\s*([\d.]+)\s*(?:lakh|lpa|lac)",
        s,
        re.IGNORECASE,
    )
    if single_match:
        val = int(float(single_match.group(1)) * 100_000)
        return val, val, is_estimated

    # Raw numbers in lakhs (e.g. "15-20" in context of lakhs)
    range_match = re.search(r"([\d.]+)\s*-\s*([\d.]+)\s*(?:lakh|lpa)?", s, re.IGNORECASE)
    if range_match:
        min_val = int(float(range_match.group(1)) * 100_000)
        max_val = int(float(range_match.group(2)) * 100_000)
        return min_val, max_val, is_estimated

    return None, None, is_estimated


class SerpAPIClient:
    """Client for SerpAPI Google Jobs engine."""

    BASE_URL = "https://serpapi.com/search"
    ENGINE = "google_jobs"

    def __init__(self, api_key: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.serpapi_key

    async def search_jobs(
        self,
        query: str,
        location: str = "India",
        num_results: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Fetch jobs from SerpAPI Google Jobs engine.
        Returns list of dicts matching scouted_jobs table schema.
        """
        if not self.api_key:
            return []

        params = {
            "engine": self.ENGINE,
            "q": query,
            "location": location,
            "api_key": self.api_key,
        }

        all_jobs: list[dict[str, Any]] = []
        next_token = None

        while len(all_jobs) < num_results:
            if next_token:
                params["next_page_token"] = next_token

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(self.BASE_URL, params=params)

            if resp.status_code != 200:
                break

            data = resp.json()

            # Check for API errors
            if data.get("error"):
                break

            jobs_results = data.get("jobs_results", [])
            if not jobs_results:
                break

            for item in jobs_results:
                if isinstance(item, dict) and "title" in item:
                    parsed = self._parse_job(item, query)
                    if parsed:
                        all_jobs.append(parsed)

            if len(all_jobs) >= num_results:
                break

            next_token = (
                data.get("serpapi_pagination", {}) or {}
            ).get("next_page_token")
            if not next_token:
                break

            # Remove next_page_token from params for subsequent requests
            params.pop("next_page_token", None)

        return all_jobs[:num_results]

    def _parse_job(self, raw: dict[str, Any], search_query: str) -> dict[str, Any] | None:
        """Convert a single SerpAPI job result to scouted_jobs schema."""
        title = raw.get("title") or ""
        company_name = raw.get("company_name") or ""
        location_str = raw.get("location") or ""

        if not title or not company_name:
            return None

        city = extract_city(location_str)
        company_norm = normalize_company(company_name)
        dedup_hash = generate_dedup_hash(company_name, title, location_str)

        # Posted date from detected_extensions
        posted_dt = None
        det = raw.get("detected_extensions") or {}
        posted_at_str = det.get("posted_at")
        if posted_at_str:
            posted_dt = parse_posted_date(posted_at_str)
        posted_date = posted_dt.date() if posted_dt else None

        # Salary from detected_extensions or description
        salary_min, salary_max, salary_is_estimated = None, None, False
        salary_str = det.get("salary")
        if salary_str:
            salary_min, salary_max, salary_is_estimated = parse_salary(salary_str)
        if salary_min is None and raw.get("description"):
            # Try to extract from description
            sal_match = re.search(
                r"(?:₹|Rs\.?|INR)?\s*([\d.]+)\s*(?:-|to)\s*([\d.]+)\s*(?:lakh|lpa)",
                raw["description"],
                re.IGNORECASE,
            )
            if sal_match:
                salary_min = int(float(sal_match.group(1)) * 100_000)
                salary_max = int(float(sal_match.group(2)) * 100_000)

        # Description - truncate to 10k chars
        description = raw.get("description") or ""
        if len(description) > 10_000:
            description = description[:10_000]

        # Apply URL - first apply_options link, or link
        apply_url = None
        apply_opts = raw.get("apply_options") or []
        if apply_opts and isinstance(apply_opts[0], dict):
            apply_url = apply_opts[0].get("link")
        if not apply_url:
            apply_url = raw.get("link")

        # Source URL - share_link or apply URL
        source_url = raw.get("share_link") or apply_url

        now = datetime.now(timezone.utc)

        return {
            "external_id": raw.get("job_id"),
            "dedup_hash": dedup_hash,
            "title": title,
            "company_name": company_name,
            "company_name_normalized": company_norm,
            "location": location_str or None,
            "city": city,
            "description": description or None,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "salary_is_estimated": salary_is_estimated,
            "source": "serpapi",
            "source_url": source_url,
            "apply_url": apply_url,
            "posted_date": posted_date,
            "scouted_at": now,
            "last_seen_at": now,
            "is_active": True,
            "raw_json": raw,
            "search_query": search_query,
        }


async def fetch_jobs_from_serpapi(
    templates: list[str] | None = None,
    locations: list[str] | None = None,
    num_results_per_query: int = 10,
) -> list[dict[str, Any]]:
    """
    Run all template x location combinations, deduplicate by hash.
    Returns combined list of unique jobs.
    """
    templates = templates or DEFAULT_SEARCH_TEMPLATES
    locations = locations or DEFAULT_LOCATIONS

    client = SerpAPIClient()
    seen_hashes: set[str] = set()
    all_jobs: list[dict[str, Any]] = []

    for template in templates:
        for loc in locations:
            query = template.format(location=loc)
            jobs = await client.search_jobs(
                query=query,
                location=loc,
                num_results=num_results_per_query,
            )
            for job in jobs:
                h = job.get("dedup_hash")
                if h and h not in seen_hashes:
                    seen_hashes.add(h)
                    all_jobs.append(job)

    return all_jobs
