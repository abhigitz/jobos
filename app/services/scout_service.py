"""Job Scout service -- automated job discovery engine."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from rapidfuzz import fuzz
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.job import Job
from app.models.company import Company
from app.models.profile import ProfileDNA
from app.models.scout_result import ScoutResult
from app.models.user import User
from app.services.ai_service import call_claude, parse_json_response

logger = logging.getLogger(__name__)


# -- Pre-filter constants --------------------------------------------------

LOCATION_KEYWORDS = [
    "bangalore", "bengaluru", "remote", "india", "work from home",
    "hybrid", "pan india", "anywhere in india",
]

SENIORITY_KEYWORDS = [
    "director", "vp", "vice president", "head of", "lead",
    "principal", "senior director", "chief", "svp", "avp",
    "general manager", "gm",
]

B2C_KEYWORDS = [
    "b2c", "consumer", "d2c", "direct to consumer", "marketplace",
    "e-commerce", "ecommerce", "fintech", "edtech", "healthtech",
    "gaming", "social", "media", "entertainment", "food",
    "delivery", "mobility", "travel", "retail",
]

EXCLUDED_KEYWORDS = [
    "staffing", "recruitment agency", "consulting firm",
    "body shopping", "manpower",
]


# -- Source Fetchers --------------------------------------------------------

async def _fetch_serper(queries: list[str], api_key: str) -> list[dict]:
    """Fetch job listings from Serper.dev Google Search API.

    Uses /search endpoint which returns organic results (title, link, snippet).
    Queries should already include 'jobs' or 'hiring' to make results job-relevant.
    """
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            try:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json={
                        "q": query,
                        "gl": "in",
                        "location": "Bangalore, Karnataka, India",
                        "type": "search",
                        "num": 10,
                    },
                )
                if resp.status_code != 200:
                    logger.error(f"Serper API error: {resp.status_code} for query '{query}'")
                    continue
                data = resp.json()
                # Serper returns organic results -- extract job-relevant ones
                for item in data.get("organic", []):
                    results.append(_normalize_serper(item))
            except Exception as e:
                logger.error(f"Serper fetch failed for '{query}': {e}")
    return [r for r in results if r is not None]


def _normalize_serper(item: dict) -> dict | None:
    """Normalize a Serper organic result to common schema.

    Maps: title -> title (parses 'Role at Company' pattern), link -> source_url, snippet -> snippet.
    Company name extracted from title using common separators.
    """
    title = item.get("title", "")
    link = item.get("link", "")
    snippet = item.get("snippet", "")

    if not title or not link:
        return None

    # Try to extract company from title (often "Role at Company" or "Role - Company")
    company = "Unknown"
    for sep in [" at ", " - ", " | ", " \u2014 "]:
        if sep in title:
            parts = title.split(sep, 1)
            company = parts[1].strip() if len(parts) > 1 else "Unknown"
            title = parts[0].strip()
            break

    return {
        "source": "serper",
        "source_url": link,
        "title": title[:500],
        "company_name": company[:500],
        "location": "",  # Serper organic doesn't always have location
        "snippet": snippet[:2000] if snippet else None,
        "salary_raw": None,
        "posted_date_raw": None,
    }


async def _fetch_adzuna(queries: list[str], app_id: str, api_key: str) -> list[dict]:
    """Fetch job listings from Adzuna India API (primary source).

    Field mapping verified against real API responses.
    """
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            try:
                resp = await client.get(
                    "https://api.adzuna.com/v1/api/jobs/in/search/1",
                    params={
                        "app_id": app_id,
                        "app_key": api_key,
                        "results_per_page": 10,
                        "what": query,
                        "where": "Bangalore",
                        "content-type": "application/json",
                    },
                )
                if resp.status_code != 200:
                    logger.error(f"Adzuna API error: {resp.status_code} for query '{query}'")
                    continue
                data = resp.json()
                for item in data.get("results", []):
                    results.append(_normalize_adzuna(item))
            except Exception as e:
                logger.error(f"Adzuna fetch failed for '{query}': {e}")
    return [r for r in results if r is not None]


def _normalize_adzuna(item: dict) -> dict | None:
    """Normalize an Adzuna result to common schema.

    Field mapping verified against real Adzuna API responses.
    """
    title = item.get("title", "")
    redirect_url = item.get("redirect_url", "")
    company_name = item.get("company", {}).get("display_name", "Unknown")
    location = item.get("location", {}).get("display_name", "")
    description = item.get("description", "")
    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")
    created = item.get("created", "")
    adzuna_id = item.get("id")  # unique Adzuna job ID for dedup fingerprint
    category_label = item.get("category", {}).get("label", "")

    if not title:
        return None

    salary_raw = None
    if salary_min and salary_max:
        salary_raw = f"{salary_min}-{salary_max}"
    elif salary_min:
        salary_raw = f"{salary_min}+"

    return {
        "source": "adzuna",
        "source_url": redirect_url[:2000] if redirect_url else None,
        "title": title[:500],
        "company_name": company_name[:500],
        "location": location[:500] if location else None,
        "snippet": description[:2000] if description else None,
        "salary_raw": salary_raw,
        "posted_date_raw": created[:100] if created else None,
        "adzuna_id": str(adzuna_id) if adzuna_id else None,
        "category_label": category_label[:200] if category_label else None,
    }


# -- Deduplication ----------------------------------------------------------

def _deduplicate(
    items: list[dict],
    existing_urls: set[str],
    existing_titles: list[tuple[str, str]],
    existing_adzuna_ids: set[str] | None = None,
) -> list[dict]:
    """Remove duplicates by Adzuna ID, URL exact match, and title+company fuzzy match.

    Args:
        items: Normalized job dicts from fetchers
        existing_urls: Set of source_urls already in scout_results or jobs table
        existing_titles: List of (title, company) tuples from existing jobs + scout_results
        existing_adzuna_ids: Set of Adzuna IDs already in scout_results
    """
    seen_urls: set[str] = set()
    seen_adzuna_ids: set[str] = set()
    seen_titles: list[tuple[str, str]] = []
    unique = []

    if existing_adzuna_ids is None:
        existing_adzuna_ids = set()

    for item in items:
        url = item.get("source_url", "")
        title = item.get("title", "")
        company = item.get("company_name", "")
        adzuna_id = item.get("adzuna_id", "")

        # 0. Adzuna ID exact match (fastest dedup for Adzuna results)
        if adzuna_id:
            if adzuna_id in existing_adzuna_ids or adzuna_id in seen_adzuna_ids:
                continue
            seen_adzuna_ids.add(adzuna_id)

        # 1. URL exact match against DB
        if url and url in existing_urls:
            continue

        # 2. URL exact match within this batch
        if url and url in seen_urls:
            continue

        # 3. Title + Company fuzzy match against DB
        is_dup = False
        for ex_title, ex_company in existing_titles:
            title_ratio = fuzz.ratio(title.lower(), ex_title.lower())
            company_ratio = fuzz.ratio(company.lower(), ex_company.lower())
            if title_ratio > 85 and company_ratio > 85:
                is_dup = True
                break

        if is_dup:
            continue

        # 4. Title + Company fuzzy match within this batch
        for s_title, s_company in seen_titles:
            title_ratio = fuzz.ratio(title.lower(), s_title.lower())
            company_ratio = fuzz.ratio(company.lower(), s_company.lower())
            if title_ratio > 85 and company_ratio > 85:
                is_dup = True
                break

        if is_dup:
            continue

        seen_urls.add(url)
        seen_titles.append((title, company))
        unique.append(item)

    return unique


# -- Pre-filter (fast, no AI cost) -----------------------------------------

def _pre_filter(
    items: list[dict],
    target_roles: list[str] | None,
    target_locations: list[str] | None,
    excluded_companies: set[str],
) -> list[dict]:
    """Fast pre-filter before AI scoring. Removes obviously irrelevant jobs."""
    passed = []
    for item in items:
        title_lower = (item.get("title", "") or "").lower()
        company_lower = (item.get("company_name", "") or "").lower()
        location_lower = (item.get("location", "") or "").lower()
        snippet_lower = (item.get("snippet", "") or "").lower()
        combined = f"{title_lower} {company_lower} {location_lower} {snippet_lower}"

        # Skip excluded companies
        if company_lower in excluded_companies:
            continue

        # Skip if company matches excluded keywords
        if any(kw in company_lower for kw in EXCLUDED_KEYWORDS):
            continue

        # Location check (if location data available)
        location_ok = True
        if location_lower:
            location_ok = any(kw in location_lower for kw in LOCATION_KEYWORDS)
            # Also check custom target_locations from profile
            if not location_ok and target_locations:
                location_ok = any(
                    loc.lower() in location_lower for loc in target_locations
                )

        if not location_ok:
            continue

        # Seniority check -- at least one seniority keyword in title
        seniority_ok = any(kw in title_lower for kw in SENIORITY_KEYWORDS)
        if not seniority_ok:
            # Also check against target_roles from profile
            if target_roles:
                seniority_ok = any(
                    fuzz.partial_ratio(role.lower(), title_lower) > 70
                    for role in target_roles
                )

        if not seniority_ok:
            continue

        # B2C keyword check (in title, company, or snippet)
        b2c_ok = any(kw in combined for kw in B2C_KEYWORDS)

        # Even if no B2C keyword, keep it -- AI will validate
        # But mark it for AI to pay attention
        item["_b2c_hint"] = b2c_ok

        passed.append(item)

    return passed


# -- AI Scoring (batch up to 5 per Claude call) ----------------------------

async def _ai_score_batch(
    items: list[dict],
    profile_summary: str,
) -> list[dict]:
    """Score a batch of up to 5 jobs using a single Claude call.

    Returns the same items with fit_score, b2c_validated, ai_reasoning added.
    """
    jobs_block = ""
    for i, item in enumerate(items):
        jobs_block += f"""
---JOB {i+1}---
Title: {item.get('title', '')}
Company: {item.get('company_name', '')}
Location: {item.get('location', '')}
Snippet: {item.get('snippet', '')[:500]}
Salary: {item.get('salary_raw', 'N/A')}
B2C hint from pre-filter: {item.get('_b2c_hint', False)}
"""

    prompt = f"""You are a job-fit scoring engine for a senior growth/marketing leader.

CANDIDATE PROFILE:
{profile_summary}

Score each job below on a 1-10 scale:
- 1-4: Poor fit (wrong level, wrong domain, wrong location)
- 5-6: Possible fit (partially matches, worth reviewing)
- 7-10: Strong fit (right level + domain + location, B2C preferred)

Also determine if the company is B2C (true/false).

{jobs_block}

Return ONLY valid JSON -- an array with one object per job:
[
  {{
    "index": 1,
    "fit_score": 7,
    "b2c_validated": true,
    "reasoning": "Brief 1-2 sentence reasoning"
  }},
  ...
]

No markdown, no explanation outside the JSON array.
"""

    raw = await call_claude(prompt, max_tokens=1500)
    parsed = parse_json_response(raw)

    if not parsed or not isinstance(parsed, list):
        logger.error("AI scoring returned invalid response, marking batch as score=0")
        for item in items:
            item["fit_score"] = 0.0
            item["b2c_validated"] = False
            item["ai_reasoning"] = "AI scoring failed"
        return items

    # Merge scores back into items
    score_map = {s.get("index", 0): s for s in parsed}
    for i, item in enumerate(items):
        score_data = score_map.get(i + 1, {})
        item["fit_score"] = float(score_data.get("fit_score", 0))
        item["b2c_validated"] = bool(score_data.get("b2c_validated", False))
        item["ai_reasoning"] = score_data.get("reasoning", "")

    return items


async def _ai_score_all(items: list[dict], profile_summary: str) -> list[dict]:
    """Score all items in batches of 5."""
    scored = []
    batch_size = 5
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        result = await _ai_score_batch(batch, profile_summary)
        scored.extend(result)
    return scored


# -- Main Orchestrator ------------------------------------------------------

async def run_scout(user_id: str | None = None) -> dict:
    """Run the full scout pipeline: FETCH -> NORMALIZE -> DEDUP -> PRE-FILTER -> AI SCORE -> SAVE + NOTIFY.

    Args:
        user_id: If provided, run for this user. Otherwise use owner from settings.

    Returns:
        ScoutRunSummary-compatible dict.
    """
    from app.tasks.db import get_task_session
    from app.services.telegram_service import send_telegram_message

    settings = get_settings()
    run_id = f"scout_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    errors: list[str] = []

    logger.info(f"Scout run {run_id} starting")

    async with get_task_session() as db:
        # 1. Resolve user
        if user_id:
            result = await db.execute(select(User).where(User.id == user_id))
        else:
            result = await db.execute(
                select(User).where(User.email == settings.owner_email)
            )
        user = result.scalar_one_or_none()
        if not user:
            logger.error(f"Scout run {run_id}: user not found")
            return {"run_id": run_id, "errors": ["User not found"]}

        # 2. Load profile for query building + AI scoring context
        profile_result = await db.execute(
            select(ProfileDNA).where(ProfileDNA.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()

        target_roles = profile.target_roles if profile and profile.target_roles else [
            "Head of Growth", "VP Growth", "Director Growth Marketing",
            "Head of Marketing", "Growth Lead",
        ]
        target_locations = profile.target_locations if profile and profile.target_locations else [
            "Bangalore", "Remote",
        ]

        # Build search queries from target_roles
        queries = [f"{role} B2C Bangalore" for role in target_roles[:5]]

        # Build profile summary for AI scoring
        profile_summary = "No detailed profile available."
        if profile:
            parts = []
            if profile.target_roles:
                parts.append(f"Target roles: {', '.join(profile.target_roles)}")
            if profile.target_locations:
                parts.append(f"Target locations: {', '.join(profile.target_locations)}")
            if profile.core_skills:
                parts.append(f"Core skills: {', '.join(profile.core_skills)}")
            if profile.industries:
                parts.append(f"Industries: {', '.join(profile.industries)}")
            if profile.experience_level:
                parts.append(f"Experience level: {profile.experience_level}")
            profile_summary = "\n".join(parts) if parts else profile_summary

        # 3. FETCH from sources (Adzuna is primary, Serper is supplementary)
        all_items: list[dict] = []
        sources_queried: list[str] = []

        # Primary source: Adzuna (structured job data, better field mapping)
        if settings.adzuna_app_id and settings.adzuna_api_key:
            adzuna_results = await _fetch_adzuna(
                queries, settings.adzuna_app_id, settings.adzuna_api_key
            )
            all_items.extend(adzuna_results)
            sources_queried.append("adzuna")
            logger.info(f"Scout {run_id}: Adzuna (primary) returned {len(adzuna_results)} results")
        else:
            errors.append("Adzuna API keys not configured, skipping")

        # Supplementary source: Serper (Google search, broader coverage)
        if settings.serper_api_key:
            serper_queries = [f"{q} jobs" for q in queries]
            serper_results = await _fetch_serper(serper_queries, settings.serper_api_key)
            all_items.extend(serper_results)
            sources_queried.append("serper")
            logger.info(f"Scout {run_id}: Serper (supplementary) returned {len(serper_results)} results")
        else:
            errors.append("Serper API key not configured, skipping")

        total_fetched = len(all_items)

        if not all_items:
            logger.warning(f"Scout {run_id}: no results fetched from any source")
            return {
                "run_id": run_id, "sources_queried": sources_queried,
                "total_fetched": 0, "after_dedup": 0, "after_prefilter": 0,
                "ai_scored": 0, "promoted_to_pipeline": 0,
                "saved_for_review": 0, "dismissed": 0, "errors": errors,
            }

        # 4. DEDUP -- load existing URLs and titles from DB
        existing_scout_urls_result = await db.execute(
            select(ScoutResult.source_url).where(
                ScoutResult.user_id == user.id,
                ScoutResult.source_url.isnot(None),
            )
        )
        existing_job_urls_result = await db.execute(
            select(Job.jd_url).where(
                Job.user_id == user.id,
                Job.jd_url.isnot(None),
                Job.is_deleted == False,
            )
        )
        existing_urls: set[str] = set()
        for row in existing_scout_urls_result.scalars().all():
            if row:
                existing_urls.add(row)
        for row in existing_job_urls_result.scalars().all():
            if row:
                existing_urls.add(row)

        existing_scout_titles_result = await db.execute(
            select(ScoutResult.title, ScoutResult.company_name).where(
                ScoutResult.user_id == user.id,
            )
        )
        existing_job_titles_result = await db.execute(
            select(Job.role_title, Job.company_name).where(
                Job.user_id == user.id,
                Job.is_deleted == False,
            )
        )
        existing_titles: list[tuple[str, str]] = []
        for row in existing_scout_titles_result.all():
            existing_titles.append((row[0] or "", row[1] or ""))
        for row in existing_job_titles_result.all():
            existing_titles.append((row[0] or "", row[1] or ""))

        # Load existing Adzuna IDs for fast dedup
        existing_adzuna_ids_result = await db.execute(
            select(ScoutResult.normalized_data["adzuna_id"].astext).where(
                ScoutResult.user_id == user.id,
                ScoutResult.source == "adzuna",
                ScoutResult.normalized_data["adzuna_id"] != None,  # noqa: E711
            )
        )
        existing_adzuna_ids: set[str] = {
            row for row in existing_adzuna_ids_result.scalars().all() if row
        }

        deduped = _deduplicate(all_items, existing_urls, existing_titles, existing_adzuna_ids)
        logger.info(f"Scout {run_id}: {len(deduped)} after dedup (from {total_fetched})")

        # 5. PRE-FILTER
        # Load excluded companies from Company table
        excluded_result = await db.execute(
            select(Company.name).where(Company.is_excluded == True)
        )
        excluded_companies = {
            name.lower() for name in excluded_result.scalars().all() if name
        }

        filtered = _pre_filter(deduped, target_roles, target_locations, excluded_companies)
        logger.info(f"Scout {run_id}: {len(filtered)} after pre-filter (from {len(deduped)})")

        # 6. AI SCORE
        scored = []
        if filtered:
            try:
                scored = await _ai_score_all(filtered, profile_summary)
            except Exception as e:
                logger.error(f"Scout {run_id}: AI scoring failed: {e}")
                errors.append(f"AI scoring error: {str(e)}")
                # Use unscored items with score=0
                scored = filtered
                for item in scored:
                    item.setdefault("fit_score", 0.0)
                    item.setdefault("b2c_validated", False)
                    item.setdefault("ai_reasoning", "Scoring unavailable")

        # 7. SAVE + CATEGORIZE
        promoted_count = 0
        review_count = 0
        dismissed_count = 0

        for item in scored:
            score = item.get("fit_score", 0.0) or 0.0

            if score >= 7:
                status = "promoted"
            elif score >= 5:
                status = "new"  # saved for review
            else:
                status = "dismissed"

            # Save to scout_results
            scout_result = ScoutResult(
                user_id=user.id,
                source=item.get("source", "unknown"),
                source_url=item.get("source_url"),
                title=item.get("title", "")[:500],
                company_name=item.get("company_name", "")[:500],
                location=item.get("location"),
                snippet=item.get("snippet"),
                salary_raw=item.get("salary_raw"),
                posted_date_raw=item.get("posted_date_raw"),
                normalized_data=item,
                fit_score=score,
                b2c_validated=item.get("b2c_validated", False),
                ai_reasoning=item.get("ai_reasoning"),
                status=status,
                scout_run_id=run_id,
            )
            db.add(scout_result)

            # Promote 7+ to jobs pipeline as "Tracking"
            if status == "promoted":
                new_job = Job(
                    user_id=user.id,
                    company_name=item.get("company_name", "Unknown")[:255],
                    role_title=item.get("title", "Unknown")[:255],
                    source_portal=item.get("source", "scout")[:100],
                    jd_url=item.get("source_url", "")[:1000] if item.get("source_url") else None,
                    jd_text=item.get("snippet"),
                    status="Tracking",
                    fit_score=score,
                    fit_reasoning=item.get("ai_reasoning"),
                    salary_range=item.get("salary_raw"),
                    notes=[{
                        "text": f"Auto-discovered by Job Scout (run {run_id}). Fit score: {score}/10.",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "type": "scout",
                    }],
                )
                db.add(new_job)
                await db.flush()  # get new_job.id
                scout_result.promoted_job_id = new_job.id
                promoted_count += 1
            elif status == "new":
                review_count += 1
            else:
                dismissed_count += 1

        await db.commit()
        logger.info(
            f"Scout {run_id} complete: {promoted_count} promoted, "
            f"{review_count} for review, {dismissed_count} dismissed"
        )

        # 8. NOTIFY via Telegram
        chat_id = settings.owner_telegram_chat_id
        if chat_id and promoted_count > 0:
            # Build notification message
            lines = [f"*Job Scout Run Complete* ({run_id})\n"]
            lines.append(f"Fetched: {total_fetched} | Deduped: {len(deduped)} | Filtered: {len(filtered)} | Scored: {len(scored)}")
            lines.append(f"*Promoted to pipeline: {promoted_count}*")
            lines.append(f"For review: {review_count} | Dismissed: {dismissed_count}\n")

            # List promoted jobs
            for item in scored:
                if (item.get("fit_score", 0) or 0) >= 7:
                    lines.append(
                        f"  {item.get('title', '?')} @ {item.get('company_name', '?')} "
                        f"-- Score: {item.get('fit_score', 0)}/10"
                    )

            try:
                await send_telegram_message(chat_id, "\n".join(lines))
            except Exception as e:
                logger.error(f"Scout {run_id}: Telegram notification failed: {e}")
                errors.append(f"Telegram notification failed: {str(e)}")
        elif chat_id and promoted_count == 0 and review_count > 0:
            try:
                await send_telegram_message(
                    chat_id,
                    f"*Job Scout* ({run_id}): No strong matches this run. "
                    f"{review_count} jobs saved for review, {dismissed_count} dismissed.",
                )
            except Exception:
                pass

    return {
        "run_id": run_id,
        "sources_queried": sources_queried,
        "total_fetched": total_fetched,
        "after_dedup": len(deduped),
        "after_prefilter": len(filtered),
        "ai_scored": len(scored),
        "promoted_to_pipeline": promoted_count,
        "saved_for_review": review_count,
        "dismissed": dismissed_count,
        "errors": errors,
    }
