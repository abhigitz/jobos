# Job Scout System -- Automated Job Discovery Engine -- Claude Code Prompt

You are working on **JobOS**, a FastAPI + SQLAlchemy 2.0 async + PostgreSQL backend deployed on Railway. The codebase uses `datetime.now(timezone.utc)` everywhere. Never use `datetime.utcnow()`. The Claude model string is `"claude-sonnet-4-20250514"`. Use `AsyncAnthropic()` (already instantiated as `client` in ai_service.py). Use `flag_modified(obj, "field")` after any in-place JSONB mutation. HTTP client is `httpx==0.28.1` (NOT aiohttp). Never use em dashes -- use `--` instead.

---

## Files you MUST read before writing any code

| File | What to learn |
|---|---|
| `app/config.py` | Pydantic `Settings(BaseSettings)` with `extra = "ignore"`. Has `owner_telegram_chat_id: int = 0`, `owner_email: str = ""`, `owner_phone: str = ""`, `owner_linkedin_url: str = ""`. You will ADD `serper_api_key` and `adzuna_app_id` + `adzuna_api_key` here. |
| `app/models/job.py` | 30 data columns. `company_name` (String 255), `role_title` (String 255), `source_portal` (String 100), `fit_score` (float), `ats_score` (float), `jd_url` (String 1000), `jd_text` (Text), `status` (String 50, CHECK constraint `ck_jobs_status_valid` for Tracking/Applied/Interview/Offer/Closed), `notes` (JSONB, `server_default='[]'`), `ai_analysis` (JSONB), `fit_reasoning` (Text), `salary_range` (String 100), `keywords_matched` (ARRAY String), `keywords_missing` (ARRAY String), `is_deleted` (Boolean). Uses `Base, IDMixin, TimestampMixin` from `app.models.base`. |
| `app/models/company.py` | `name` (String 255), `lane` (int, NOT nullable, CHECK 1-3), `sector` (String 100), `b2c_validated` (Boolean), `hq_city` (String 100), `is_excluded` (Boolean). |
| `app/models/profile.py` | Class `ProfileDNA`, table `profile_dna`. Has `target_roles` (ARRAY String), `target_locations` (ARRAY String), `core_skills` (ARRAY String), `industries` (ARRAY String), `experience_level` (String 50), `resume_keywords` (ARRAY String), `raw_resume_text` (Text). Import as `from app.models.profile import ProfileDNA`. |
| `app/models/base.py` | `Base(DeclarativeBase)`, `IDMixin` (UUID pk, `default=uuid.uuid4`), `TimestampMixin` (`created_at`, `updated_at` with `server_default=func.now()`, `onupdate=func.now()`). |
| `app/models/__init__.py` | Imports all 15 models. You will ADD `ScoutResult` here. |
| `app/schemas/jobs.py` | `JobCreate`, `JobOut` (27 fields, `from_attributes = True`), `JobUpdate`, `PaginatedResponse`. |
| `app/services/ai_service.py` | `call_claude(prompt, max_tokens=2000)` with retry decorator. `parse_json_response(text)`. `LEVEL_CONTEXT` dict. 13+ async functions. You will ADD `score_scout_jobs()` here. |
| `app/services/telegram_service.py` | `send_telegram_message(chat_id, text)` -- already supports `parse_mode="Markdown"`, auto-splits >4096 chars. |
| `app/tasks/db.py` | `get_task_session()` async context manager using `AsyncSessionLocal`. Pattern: `async with get_task_session() as db:` |
| `app/tasks/morning_briefing.py` | Reference task pattern: `settings = get_settings()`, get `chat_id` + `owner_email`, find User, query DB, call AI, send Telegram, try/except outer block. |
| `app/tasks/auto_ghost.py` | Reference task pattern: same DB session pattern, `flag_modified()` for JSONB, `await db.commit()` inside the `async with` block. |
| `app/scheduler.py` | 6 tasks registered via lazy imports in `register_jobs()`. Pattern: `scheduler.add_job(func, CronTrigger(...), id="name", replace_existing=True, misfire_grace_time=300)`. |
| `app/routers/telegram.py` | 309 lines. Webhook handler with if/elif command chain. Test commands at lines 257-285. Default "Unknown command" at line 287. You will ADD `/scout` command and `/test-scout` command. |
| `app/routers/jobs.py` | 887 lines. Fixed-path routes before parametric routes. Route order: `GET ""`, `POST "/"`, `GET /pipeline`, `GET /stale`, `GET /followups`, `POST /analyze-jd`, `POST /save-from-analysis`, `POST /deep-resume-analysis`, `GET /search`, then `GET /{job_id}`, `PATCH /{job_id}`, etc. You will ADD `GET /scout-results` and `POST /scout-promote/{scout_id}` in the FIXED-PATH section. |
| `app/main.py` | Router registration at lines 54-80. You will ADD `scout` router here. |
| `app/database.py` | `AsyncSessionLocal = async_sessionmaker(...)`. `get_db()` yields session. |
| `alembic/versions/d4e5f6a7b8c9_jd_analyzer_redesign_phase_a.py` | **HEAD migration**. `revision = 'd4e5f6a7b8c9'`, `down_revision = 'c3d4e5f6a7b8'`. New migration MUST use `down_revision = 'd4e5f6a7b8c9'`. |
| `requirements.txt` | Has `httpx==0.28.1`. Does NOT have `rapidfuzz`. You will ADD `rapidfuzz>=3.0,<4.0`. |

---

## STEP 0 -- Verify External API Response Structures (DO THIS FIRST)

Before writing ANY production code, create two throwaway test scripts to verify the actual response shapes from Serper.dev and Adzuna. These APIs may change their response format -- do NOT trust the spec blindly.

### 0a. Create `test_serper.py` (project root, NOT in app/)

```python
"""Throwaway script to verify Serper.dev Google Jobs API response structure."""
import asyncio
import json
import os

import httpx


async def test_serper():
    api_key = os.environ.get("SERPER_API_KEY", "")
    if not api_key:
        print("ERROR: Set SERPER_API_KEY env var first")
        return

    async with httpx.AsyncClient() as client:
        # Test Google Jobs search
        resp = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={
                "q": "Head of Growth B2C Bangalore",
                "gl": "in",
                "location": "Bangalore, Karnataka, India",
                "type": "search",
                "num": 5,
            },
        )
        print(f"Status: {resp.status_code}")
        data = resp.json()
        print(json.dumps(data, indent=2))

        # Print the keys at each level so we know the exact structure
        print("\n--- TOP-LEVEL KEYS ---")
        print(list(data.keys()))

        if "organic" in data:
            print("\n--- FIRST ORGANIC RESULT KEYS ---")
            print(list(data["organic"][0].keys()))

        if "jobs" in data:
            print("\n--- FIRST JOB RESULT KEYS ---")
            print(list(data["jobs"][0].keys()))


asyncio.run(test_serper())
```

Run: `SERPER_API_KEY=your_key python3 test_serper.py`

**IMPORTANT:** Examine the output. The response may have jobs under `"organic"` or `"jobs"` or another key. The field names for title, company, location, link may differ from what you expect. Adapt `_normalize_serper()` in Task D accordingly.

### 0b. Create `test_adzuna.py` (project root, NOT in app/)

```python
"""Throwaway script to verify Adzuna API response structure."""
import asyncio
import json
import os

import httpx


async def test_adzuna():
    app_id = os.environ.get("ADZUNA_APP_ID", "")
    api_key = os.environ.get("ADZUNA_API_KEY", "")
    if not app_id or not api_key:
        print("ERROR: Set ADZUNA_APP_ID and ADZUNA_API_KEY env vars first")
        return

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.adzuna.com/v1/api/jobs/in/search/1",
            params={
                "app_id": app_id,
                "app_key": api_key,
                "results_per_page": 5,
                "what": "Head of Growth",
                "where": "Bangalore",
                "content-type": "application/json",
            },
        )
        print(f"Status: {resp.status_code}")
        data = resp.json()
        print(json.dumps(data, indent=2))

        print("\n--- TOP-LEVEL KEYS ---")
        print(list(data.keys()))

        if "results" in data:
            print("\n--- FIRST RESULT KEYS ---")
            print(list(data["results"][0].keys()))


asyncio.run(test_adzuna())
```

Run: `ADZUNA_APP_ID=your_id ADZUNA_API_KEY=your_key python3 test_adzuna.py`

**After running both scripts:** Note the exact response structure and field names. Use those exact field names in the normalizer functions in Task D. Delete both test files when done.

---

## Task A -- Add API Keys to Config + Install rapidfuzz

### A1. Config

**File:** `app/config.py`

Find:
```python
    owner_phone: str = ""
    owner_linkedin_url: str = ""
```

Replace with:
```python
    owner_phone: str = ""
    owner_linkedin_url: str = ""
    serper_api_key: str = ""
    adzuna_app_id: str = ""
    adzuna_api_key: str = ""
```

### A2. Install rapidfuzz

Run: `pip install "rapidfuzz>=3.0,<4.0"`

Then add to `requirements.txt` after the `pydantic_core` line:
```
rapidfuzz>=3.0,<4.0
```

---

## Task B -- Alembic Migration (scout_results table)

**Create file:** `alembic/versions/e5f6a7b8c9d0_job_scout_system.py`

```python
"""Job Scout system -- scout_results table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-02-12 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scout_results',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('source_url', sa.String(2000), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('company_name', sa.String(500), nullable=False),
        sa.Column('location', sa.String(500), nullable=True),
        sa.Column('snippet', sa.Text(), nullable=True),
        sa.Column('salary_raw', sa.String(200), nullable=True),
        sa.Column('posted_date_raw', sa.String(100), nullable=True),
        sa.Column('normalized_data', JSONB, nullable=True),
        sa.Column('fit_score', sa.Float(), nullable=True),
        sa.Column('b2c_validated', sa.Boolean(), default=False),
        sa.Column('ai_reasoning', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='new'),
        sa.Column('promoted_job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('scout_run_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('new', 'reviewed', 'promoted', 'dismissed')",
            name='ck_scout_results_status_valid',
        ),
    )
    # Index for fast lookups by user + status
    op.create_index('ix_scout_results_user_status', 'scout_results', ['user_id', 'status'])
    # Index for dedup by source_url
    op.create_index('ix_scout_results_source_url', 'scout_results', ['source_url'])


def downgrade() -> None:
    op.drop_index('ix_scout_results_source_url')
    op.drop_index('ix_scout_results_user_status')
    op.drop_table('scout_results')
```

After creating, run: `alembic upgrade head`

---

## Task C -- ScoutResult Model + Schema

### C1. Create Model

**Create file:** `app/models/scout_result.py`

```python
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IDMixin, TimestampMixin


class ScoutResult(Base, IDMixin, TimestampMixin):
    __tablename__ = "scout_results"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500))
    snippet: Mapped[str | None] = mapped_column(Text)
    salary_raw: Mapped[str | None] = mapped_column(String(200))
    posted_date_raw: Mapped[str | None] = mapped_column(String(100))
    normalized_data: Mapped[dict | None] = mapped_column(JSONB)
    fit_score: Mapped[float | None] = mapped_column(Float)
    b2c_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_reasoning: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), server_default="new")
    promoted_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    scout_run_id: Mapped[str | None] = mapped_column(String(50))

    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'reviewed', 'promoted', 'dismissed')",
            name="ck_scout_results_status_valid",
        ),
    )
```

### C2. Register in models/__init__.py

**File:** `app/models/__init__.py`

Find:
```python
from .password_reset_token import PasswordResetToken
```

Add after it:
```python
from .scout_result import ScoutResult
```

Find:
```python
    "PasswordResetToken",
]
```

Replace with:
```python
    "PasswordResetToken",
    "ScoutResult",
]
```

### C3. Create Schema

**Create file:** `app/schemas/scout.py`

```python
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ScoutResultOut(BaseModel):
    id: UUID
    source: str
    source_url: Optional[str] = None
    title: str
    company_name: str
    location: Optional[str] = None
    snippet: Optional[str] = None
    salary_raw: Optional[str] = None
    posted_date_raw: Optional[str] = None
    fit_score: Optional[float] = None
    b2c_validated: bool = False
    ai_reasoning: Optional[str] = None
    status: str
    promoted_job_id: Optional[UUID] = None
    scout_run_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScoutRunSummary(BaseModel):
    """Summary returned after a scout run completes."""
    run_id: str
    sources_queried: list[str]
    total_fetched: int
    after_dedup: int
    after_prefilter: int
    ai_scored: int
    promoted_to_pipeline: int
    saved_for_review: int
    dismissed: int
    errors: list[str] = Field(default_factory=list)


class ScoutResultsPage(BaseModel):
    items: list[ScoutResultOut]
    total: int
    page: int
    per_page: int
```

---

## Task D -- Job Scout Service (Core Engine)

**Create file:** `app/services/scout_service.py`

This is the main engine. It handles: fetch from sources, normalize, dedup, pre-filter, AI score, save + notify.

```python
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


# ── Pre-filter constants ──────────────────────────────────────────────

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


# ── Source Fetchers ───────────────────────────────────────────────────

async def _fetch_serper(queries: list[str], api_key: str) -> list[dict]:
    """Fetch job listings from Serper.dev (Google search API).

    IMPORTANT: Adapt field names based on test_serper.py output.
    The fields below are best-guess -- verify against actual API response.
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

    ADAPT THESE FIELD NAMES based on test_serper.py output.
    """
    title = item.get("title", "")
    link = item.get("link", "")
    snippet = item.get("snippet", "")

    if not title or not link:
        return None

    # Try to extract company from title (often "Role at Company" or "Role - Company")
    company = "Unknown"
    for sep in [" at ", " - ", " | ", " — "]:
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
    """Fetch job listings from Adzuna India API.

    IMPORTANT: Adapt field names based on test_adzuna.py output.
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

    ADAPT THESE FIELD NAMES based on test_adzuna.py output.
    """
    title = item.get("title", "")
    redirect_url = item.get("redirect_url", "")
    company_name = item.get("company", {}).get("display_name", "Unknown")
    location = item.get("location", {}).get("display_name", "")
    description = item.get("description", "")
    salary_min = item.get("salary_min")
    salary_max = item.get("salary_max")
    created = item.get("created", "")

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
    }
```

**Continue adding to the SAME file** `app/services/scout_service.py` -- append after the `_normalize_adzuna` function:

```python
# ── Deduplication ─────────────────────────────────────────────────────

def _deduplicate(items: list[dict], existing_urls: set[str], existing_titles: list[tuple[str, str]]) -> list[dict]:
    """Remove duplicates by URL exact match and title+company fuzzy match.

    Args:
        items: Normalized job dicts from fetchers
        existing_urls: Set of source_urls already in scout_results or jobs table
        existing_titles: List of (title, company) tuples from existing jobs + scout_results
    """
    seen_urls: set[str] = set()
    seen_titles: list[tuple[str, str]] = []
    unique = []

    for item in items:
        url = item.get("source_url", "")
        title = item.get("title", "")
        company = item.get("company_name", "")

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


# ── Pre-filter (fast, no AI cost) ────────────────────────────────────

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
```

**Continue adding to the SAME file** `app/services/scout_service.py` -- append after `_pre_filter`:

```python
# -- AI Scoring (batch up to 5 per Claude call) -------------------------

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


# -- Main Orchestrator ---------------------------------------------------

async def run_scout(user_id: str | None = None) -> dict:
    """Run the full scout pipeline: FETCH -> NORMALIZE -> DEDUP -> PRE-FILTER -> AI SCORE -> SAVE + NOTIFY.

    Args:
        user_id: If provided, run for this user. Otherwise use owner from settings.

    Returns:
        ScoutRunSummary-compatible dict.
    """
    from app.tasks.db import get_task_session

    settings = get_settings()
    run_id = f"scout_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    errors: list[str] = []

    logger.info(f"Scout run {run_id} starting")

    async with get_task_session() as db:
        # 1. Resolve user
        if user_id:
            from sqlalchemy.dialects.postgresql import UUID as PgUUID
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

        # 3. FETCH from sources
        all_items: list[dict] = []
        sources_queried: list[str] = []

        if settings.serper_api_key:
            serper_results = await _fetch_serper(queries, settings.serper_api_key)
            all_items.extend(serper_results)
            sources_queried.append("serper")
            logger.info(f"Scout {run_id}: Serper returned {len(serper_results)} results")
        else:
            errors.append("Serper API key not configured, skipping")

        if settings.adzuna_app_id and settings.adzuna_api_key:
            adzuna_results = await _fetch_adzuna(
                queries, settings.adzuna_app_id, settings.adzuna_api_key
            )
            all_items.extend(adzuna_results)
            sources_queried.append("adzuna")
            logger.info(f"Scout {run_id}: Adzuna returned {len(adzuna_results)} results")
        else:
            errors.append("Adzuna API keys not configured, skipping")

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

        deduped = _deduplicate(all_items, existing_urls, existing_titles)
        logger.info(f"Scout {run_id}: {len(deduped)} after dedup (from {total_fetched})")
```

**Continue appending** to `run_scout()` in the same file -- this is still inside `async with get_task_session() as db:`:

```python
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
```

This completes `app/services/scout_service.py`.

---

## Task E -- Scout Router

**Create file:** `app/routers/scout.py`

```python
"""Scout results API endpoints."""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.job import Job
from app.models.scout_result import ScoutResult
from app.schemas.scout import ScoutResultOut, ScoutResultsPage, ScoutRunSummary
from app.services.scout_service import run_scout

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/results", response_model=ScoutResultsPage)
async def list_scout_results(
    status: str | None = Query(None, description="Filter by status: new, reviewed, promoted, dismissed"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List scout results with optional status filter."""
    query = select(ScoutResult).where(
        ScoutResult.user_id == current_user.id,
    ).order_by(ScoutResult.created_at.desc())

    if status:
        query = query.where(ScoutResult.status == status)

    # Count total
    count_query = select(func.count()).select_from(
        query.subquery()
    )
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()

    return ScoutResultsPage(
        items=[ScoutResultOut.model_validate(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/run", response_model=ScoutRunSummary)
async def trigger_scout_run(
    current_user=Depends(get_current_user),
):
    """Manually trigger a scout run for the current user."""
    summary = await run_scout(user_id=str(current_user.id))
    return ScoutRunSummary(**summary)


@router.post("/promote/{scout_id}", response_model=ScoutResultOut)
async def promote_scout_result(
    scout_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Promote a scout result to the jobs pipeline as Tracking."""
    scout = await db.get(ScoutResult, str(scout_id))
    if not scout or scout.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Scout result not found")

    if scout.status == "promoted":
        raise HTTPException(status_code=400, detail="Already promoted")

    # Create job from scout result
    new_job = Job(
        user_id=current_user.id,
        company_name=(scout.company_name or "Unknown")[:255],
        role_title=(scout.title or "Unknown")[:255],
        source_portal=(scout.source or "scout")[:100],
        jd_url=scout.source_url[:1000] if scout.source_url else None,
        jd_text=scout.snippet,
        status="Tracking",
        fit_score=scout.fit_score,
        fit_reasoning=scout.ai_reasoning,
        salary_range=scout.salary_raw,
        notes=[{
            "text": f"Promoted from Job Scout. Original score: {scout.fit_score}/10.",
            "created_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "type": "scout",
        }],
    )
    db.add(new_job)
    await db.flush()

    scout.status = "promoted"
    scout.promoted_job_id = new_job.id
    await db.commit()
    await db.refresh(scout)

    return ScoutResultOut.model_validate(scout)


@router.patch("/dismiss/{scout_id}", response_model=ScoutResultOut)
async def dismiss_scout_result(
    scout_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Mark a scout result as dismissed."""
    scout = await db.get(ScoutResult, str(scout_id))
    if not scout or scout.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Scout result not found")

    scout.status = "dismissed"
    await db.commit()
    await db.refresh(scout)

    return ScoutResultOut.model_validate(scout)
```

---

## Task F -- Telegram `/scout` Command

**File:** `app/routers/telegram.py`

### F1. Add `/scout` and `/test-scout` commands

Find the block that ends with:
```python
    if command == "/test-ghost":
        from app.tasks.auto_ghost import auto_ghost_task
        await auto_ghost_task()
        return {"ok": True}
```

Add AFTER it (before the `await send_telegram_message(chat_id, "Unknown command. Use /help.")` line):

```python
    if command == "/scout":
        if not user:
            await send_telegram_message(chat_id, "Connect first: /connect your@email.com")
            return {"ok": True}
        await send_telegram_message(chat_id, "Starting Job Scout run... this may take a minute.")
        try:
            from app.services.scout_service import run_scout
            summary = await run_scout(user_id=str(user.id))
            msg = (
                f"*Scout complete* (run {summary.get('run_id', '?')})\n"
                f"Fetched: {summary.get('total_fetched', 0)}\n"
                f"After dedup: {summary.get('after_dedup', 0)}\n"
                f"After filter: {summary.get('after_prefilter', 0)}\n"
                f"AI scored: {summary.get('ai_scored', 0)}\n"
                f"*Promoted: {summary.get('promoted_to_pipeline', 0)}*\n"
                f"Review: {summary.get('saved_for_review', 0)}\n"
                f"Dismissed: {summary.get('dismissed', 0)}"
            )
            await send_telegram_message(chat_id, msg)
        except Exception as e:
            logger.error(f"Scout command failed: {e}")
            await send_telegram_message(chat_id, f"Scout run failed: {str(e)[:200]}")
        return {"ok": True}

    if command == "/test-scout":
        from app.services.scout_service import run_scout
        await run_scout()
        return {"ok": True}
```

### F2. Update the `/help` command

Find:
```python
    if command == "/help":
        await send_telegram_message(
            chat_id,
            "/connect email\n/disconnect\n/jd <job description>\n/apply Company | Role | URL | Source\n/status Company | NewStatus\n/pipeline\n/profile <resume>\n/log 3,4,3,y,1,2,y,Company\n/test-evening - Test evening check-in now\n/test-midday - Test midday check now\n/test-morning - Test morning briefing\n/test-content - Test LinkedIn content draft\n/test-review - Test weekly review",
        )
        return {"ok": True}
```

Replace with:
```python
    if command == "/help":
        await send_telegram_message(
            chat_id,
            "/connect email\n/disconnect\n/jd <job description>\n/apply Company | Role | URL | Source\n/status Company | NewStatus\n/pipeline\n/profile <resume>\n/scout - Run Job Scout now\n/log 3,4,3,y,1,2,y,Company\n/test-evening - Test evening check-in now\n/test-midday - Test midday check now\n/test-morning - Test morning briefing\n/test-content - Test LinkedIn content draft\n/test-review - Test weekly review\n/test-scout - Test scout run\n/test-ghost - Test auto-ghost",
        )
        return {"ok": True}
```

---

## Task G -- Scheduler Registration

**File:** `app/scheduler.py`

### G1. Add lazy import

Find:
```python
    from app.tasks.auto_ghost import auto_ghost_task
```

Add after it:
```python
    from app.tasks.scout_run import scout_run_task
```

### G2. Add scheduled job (2x daily: 6 AM IST = 0:30 UTC and 6 PM IST = 12:30 UTC)

Add after the `auto_ghost` `scheduler.add_job(...)` block:

```python
    # Job Scout: 6:00 AM IST = 0:30 AM UTC, Mon-Sat
    # Job Scout: 6:00 PM IST = 12:30 PM UTC, Mon-Sat
    scheduler.add_job(
        scout_run_task,
        CronTrigger(hour=0, minute=30, day_of_week="mon-sat"),
        id="scout_morning",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        scout_run_task,
        CronTrigger(hour=12, minute=30, day_of_week="mon-sat"),
        id="scout_evening",
        replace_existing=True,
        misfire_grace_time=300,
    )
```

### G3. Update logger.info

Find:
```python
    logger.info(
        "Scheduler jobs registered: "
        "auto_ghost (02:55 UTC), morning (03:00 UTC), midday (08:30 UTC), "
        "evening (13:00 UTC), linkedin (13:30 UTC), "
        "weekly (Sun 03:30 UTC)"
    )
```

Replace with:
```python
    logger.info(
        "Scheduler jobs registered: "
        "scout_morning (00:30 UTC), scout_evening (12:30 UTC), "
        "auto_ghost (02:55 UTC), morning (03:00 UTC), midday (08:30 UTC), "
        "evening (13:00 UTC), linkedin (13:30 UTC), "
        "weekly (Sun 03:30 UTC)"
    )
```

---

## Task H -- Scout Run Task (scheduler wrapper)

**Create file:** `app/tasks/scout_run.py`

```python
"""Scheduled task wrapper for Job Scout runs."""
import logging

from app.services.scout_service import run_scout

logger = logging.getLogger(__name__)


async def scout_run_task() -> None:
    """Wrapper called by APScheduler. Runs scout for the owner user."""
    logger.info("Scheduled scout run starting")
    try:
        summary = await run_scout()
        logger.info(
            f"Scheduled scout run complete: "
            f"promoted={summary.get('promoted_to_pipeline', 0)}, "
            f"review={summary.get('saved_for_review', 0)}, "
            f"dismissed={summary.get('dismissed', 0)}"
        )
    except Exception as e:
        logger.error(f"Scheduled scout run failed: {e}", exc_info=True)
```

---

## Task I -- Register Scout Router in main.py

**File:** `app/main.py`

### I1. Add import

Find:
```python
from .routers import (  # noqa: E402
    analytics,
    auth,
    briefing,
    briefings_user,
    companies,
    contacts,
    content,
    daily_logs,
    interviews,
    jobs,
    profile,
    telegram,
)
```

Replace with:
```python
from .routers import (  # noqa: E402
    analytics,
    auth,
    briefing,
    briefings_user,
    companies,
    contacts,
    content,
    daily_logs,
    interviews,
    jobs,
    profile,
    scout,
    telegram,
)
```

### I2. Add router registration

Find:
```python
app.include_router(interviews.router, prefix="/api/interviews", tags=["interviews"])
```

Add after it:
```python
app.include_router(scout.router, prefix="/api/scout", tags=["scout"])
```

---

## Critical Constraints -- DO NOT VIOLATE

1. **DB session pattern**: In tasks (scheduled jobs), ALWAYS use `async with get_task_session() as db:` from `app.tasks.db`. In routers, use `db: AsyncSession = Depends(get_db)`. NEVER mix these up.

2. **JSONB mutation**: If you mutate a JSONB column in-place (e.g., `job.notes.append(...)`), you MUST call `flag_modified(job, "notes")` before `await db.commit()`. Without it, SQLAlchemy won't detect the change.

3. **Datetime**: ALWAYS use `datetime.now(timezone.utc)`. NEVER use `datetime.utcnow()` -- it returns a naive datetime.

4. **Route order**: Fixed-path routes MUST come before parametric routes in any router file. E.g., `GET /results` before `GET /{scout_id}`. FastAPI matches routes top-to-bottom.

5. **Claude model string**: Always use `"claude-sonnet-4-20250514"`. This is already set in `call_claude()` -- just use `call_claude()`.

6. **Scheduler times**: All `CronTrigger` times in UTC. Railway runs UTC. IST = UTC + 5:30.

7. **Em dashes**: NEVER use em dashes (--) anywhere in code or strings. Use two hyphens `--` instead.

8. **No hardcoded API keys**: All secrets come from `get_settings()` which reads env vars.

9. **String truncation**: Always truncate strings before inserting into DB: `title[:500]`, `company_name[:500]`, `source_url[:2000]`, etc. Match the column widths defined in the migration.

10. **Import patterns**: In tasks/scheduler, use lazy imports inside `register_jobs()` or inside the task function to avoid circular imports. In routers, import at the top of the file.

---

## What NOT to Change

| File | Do NOT modify |
|---|---|
| `app/models/base.py` | Do not change `Base`, `IDMixin`, `TimestampMixin` in any way |
| `app/database.py` | Do not change the session factory or `get_db()` |
| `app/tasks/db.py` | Do not change `get_task_session()` |
| Any existing migration in `alembic/versions/` | NEVER edit existing migration files |
| `app/routers/jobs.py` | Do NOT add scout endpoints here. They go in `app/routers/scout.py` |
| `app/services/ai_service.py` | Do NOT modify existing functions. Only ADD `score_scout_jobs()` if needed -- but the current design uses `call_claude()` + `parse_json_response()` directly inside `scout_service.py`, so you likely do NOT need to modify `ai_service.py` at all |
| `app/models/job.py` | Do not modify. ScoutResult is a new table, not a modification of jobs |
| `app/models/company.py` | Do not modify |
| `app/models/profile.py` | Do not modify |

---

## Execution Order

Execute tasks in this exact order to avoid import/dependency errors:

1. **STEP 0**: Create and run `test_serper.py` and `test_adzuna.py`. Note actual field names. Delete after.
2. **Task A**: Config + install rapidfuzz
3. **Task B**: Alembic migration. Run `alembic upgrade head`.
4. **Task C**: ScoutResult model + schema + `__init__.py` registration
5. **Task D**: `app/services/scout_service.py` (adapt normalizer field names from Step 0)
6. **Task H**: `app/tasks/scout_run.py` (scheduler wrapper -- depends on Task D)
7. **Task E**: `app/routers/scout.py` (depends on Tasks C + D)
8. **Task I**: Register scout router in `app/main.py` (depends on Task E)
9. **Task F**: Telegram commands (depends on Task D)
10. **Task G**: Scheduler registration (depends on Task H)

---

## Summary of Files

| Action | File |
|---|---|
| CREATE | `test_serper.py` (temp, delete after Step 0) |
| CREATE | `test_adzuna.py` (temp, delete after Step 0) |
| MODIFY | `app/config.py` (add 3 API key settings) |
| MODIFY | `requirements.txt` (add `rapidfuzz>=3.0,<4.0`) |
| CREATE | `alembic/versions/e5f6a7b8c9d0_job_scout_system.py` |
| CREATE | `app/models/scout_result.py` |
| MODIFY | `app/models/__init__.py` (add ScoutResult import + __all__) |
| CREATE | `app/schemas/scout.py` |
| CREATE | `app/services/scout_service.py` |
| CREATE | `app/tasks/scout_run.py` |
| CREATE | `app/routers/scout.py` |
| MODIFY | `app/main.py` (import + register scout router) |
| MODIFY | `app/routers/telegram.py` (add /scout, /test-scout, update /help) |
| MODIFY | `app/scheduler.py` (add scout_morning + scout_evening jobs) |

**Total: 8 new files, 6 modified files.**

