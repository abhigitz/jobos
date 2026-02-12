# JD Analyzer Redesign -- Phase A (Backend Foundation) -- Claude Code Prompt

You are working on **JobOS**, a FastAPI + SQLAlchemy 2.0 async + PostgreSQL backend. The codebase uses `datetime.now(timezone.utc)` everywhere. Never use `datetime.utcnow()`. The Claude model string is `"claude-sonnet-4-20250514"`. Use `AsyncAnthropic()` (already instantiated as `client` in ai_service.py). Use `flag_modified(obj, "field")` after any in-place JSONB mutation.

---

## Files you MUST read before writing any code

| File | What to learn |
|---|---|
| `app/config.py` | Pydantic `Settings(BaseSettings)` with `extra = "ignore"`. Currently has `owner_telegram_chat_id: int = 0` and `owner_email: str = ""`. NO `owner_phone` or `owner_linkedin_url` yet. |
| `app/models/job.py` | 24 data columns. `fit_score`, `ats_score`, `keywords_matched`, `keywords_missing`, `ai_analysis` (JSONB), `cover_letter` (Text) exist. NO `fit_reasoning` column. NO `salary_range` column. CHECK constraint named `ck_jobs_status_valid`. `notes` is JSONB with `server_default='[]'`. |
| `app/models/company.py` | `name: Mapped[str] = mapped_column(String(255))`. `lane: Mapped[int]` (NOT nullable). CHECK constraint `ck_companies_lane_valid` for lane IN (1,2,3). NO unique constraint on name. |
| `app/models/profile.py` | Class `ProfileDNA`, table `profile_dna`. Has `core_skills` (ARRAY String), `resume_keywords` (ARRAY String), `raw_resume_text` (Text), `experience_level` (String 50), `full_name`, `positioning_statement`. Import as `from app.models.profile import ProfileDNA`. |
| `app/schemas/jobs.py` | `JDAnalyzeRequest(jd_text, jd_url)`, `JobCreate(company_name aliased as "company", role_title aliased as "role")`, `JobUpdate` (18 optional fields), `JobOut` (27 fields, `from_attributes = True`), `NoteEntry`, `AddNoteRequest`, `PaginatedResponse`. |
| `app/schemas/companies.py` | `CompanyCreate(name, lane, stage, sector, website, b2c_validated, hq_city, notes)`, `CompanyOut`, `CompanySearchResult(id, name, lane, sector, hq_city)`, `CompanyUpdate`. |
| `app/services/ai_service.py` | `call_claude(prompt, max_tokens=2000)` with retry decorator. `parse_json_response(text)`. `analyze_jd(jd_text, profile)` returns dict with 10 fields. `LEVEL_CONTEXT` dict for experience levels. 13 async functions total. |
| `app/routers/jobs.py` | 742 lines. `POST /analyze-jd` (line 285) calls `analyze_jd()` then auto-creates/updates Job. `PATCH /{job_id}` (line 431) has status change logic. Fixed-path routes before parametric routes pattern. Uses `job_id: str` (NOT UUID). Imports `from app.services.activity_log import log_activity`. |
| `app/routers/companies.py` | 138 lines. `GET /search` (line 52) uses `ilike`. `POST /` (line 29) has case-insensitive dedup. Fixed paths (`/search`) before parametric (`/{company_id}`) at line 71. |
| `app/routers/telegram.py` | Line 13: `from app.routers.jobs import analyze_jd_endpoint`. Line 88-98: `/jd` command calls `analyze_jd_endpoint()` directly, formats response as `ATS score: X, Fit: Y`. Test commands at lines 210-233. Default "Unknown command" at line 235. |
| `app/scheduler.py` | 84 lines. `register_jobs()` uses lazy imports. `CronTrigger` with UTC times. 5 existing tasks. Pattern: `scheduler.add_job(func, CronTrigger(...), id="name", replace_existing=True, misfire_grace_time=300)`. |
| `app/tasks/db.py` | `get_task_session()` async context manager using `AsyncSessionLocal`. |
| `app/services/activity_log.py` | `log_activity(db, user_id, action_type, description, related_job_id=None, related_contact_id=None)` -- calls `db.add()` and `db.flush()`. |
| `alembic/versions/c3d4e5f6a7b8_jobs_status_overhaul_and_notes_jsonb.py` | **HEAD migration**. `revision = 'c3d4e5f6a7b8'`, `down_revision = 'b2c3d4e5f6a7'`. New migration MUST use `down_revision = 'c3d4e5f6a7b8'`. |

---

## Task A -- Add owner_phone and owner_linkedin_url to Settings

**File:** `app/config.py`

Find this block:
```python
owner_telegram_chat_id: int = 0
owner_email: str = ""
```

Replace with:
```python
owner_telegram_chat_id: int = 0
owner_email: str = ""
owner_phone: str = ""
owner_linkedin_url: str = ""
```

These are used in Task E to replace cover letter signature placeholders. **Do NOT hardcode phone numbers or LinkedIn URLs anywhere in the codebase.**

---

## Task B -- Alembic Migration

**Create file:** `alembic/versions/d4e5f6a7b8c9_jd_analyzer_redesign_phase_a.py`

```python
"""JD Analyzer redesign Phase A -- new columns and pg_trgm

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Enable pg_trgm extension for fuzzy company search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Step 2: Add new columns to jobs
    op.add_column('jobs', sa.Column('fit_reasoning', sa.Text(), nullable=True))
    op.add_column('jobs', sa.Column('salary_range', sa.String(100), nullable=True))

    # Step 3: Create trigram GIN index on companies.name for fuzzy search
    op.execute(
        "CREATE INDEX ix_companies_name_trgm ON companies USING gin (name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_companies_name_trgm")
    op.drop_column('jobs', 'salary_range')
    op.drop_column('jobs', 'fit_reasoning')
    # Do NOT drop pg_trgm extension -- may be used by other things
```

---

## Task C -- Update Job Model and Schemas

### C1. Job Model

**File:** `app/models/job.py`

Find this block:
```python
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB)
    applied_date: Mapped[date | None] = mapped_column(Date())
```

Replace with:
```python
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB)
    fit_reasoning: Mapped[str | None] = mapped_column(Text)
    salary_range: Mapped[str | None] = mapped_column(String(100))
    applied_date: Mapped[date | None] = mapped_column(Date())
```

### C2. Job Schemas

**File:** `app/schemas/jobs.py`

**C2a.** Update `JobOut` -- find:
```python
    ai_analysis: Optional[dict] = None
    applied_date: Optional[date] = None
```

Replace with:
```python
    ai_analysis: Optional[dict] = None
    fit_reasoning: Optional[str] = None
    salary_range: Optional[str] = None
    applied_date: Optional[date] = None
```

**C2b.** Add new schemas AFTER the `JDAnalyzeRequest` class (after line 10). Insert these new classes:

```python
class SaveFromAnalysisRequest(BaseModel):
    """Used by POST /save-from-analysis to create a Job from analysis results."""
    company_name: str = Field(..., max_length=255)
    role_title: str = Field(..., max_length=255)
    jd_text: str = Field(..., min_length=100, max_length=15000)
    jd_url: Optional[str] = Field(None, max_length=1000)
    source_portal: str = Field("JD Analysis", max_length=100)
    # Analysis results to store
    fit_score: Optional[float] = None
    ats_score: Optional[float] = None
    fit_reasoning: Optional[str] = None
    salary_range: Optional[str] = None
    keywords_matched: Optional[list[str]] = None
    keywords_missing: Optional[list[str]] = None
    ai_analysis: Optional[dict] = None
    cover_letter: Optional[str] = None

    @field_validator("fit_score")
    @classmethod
    def validate_fit_score(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 10.0):
            raise ValueError("fit_score must be between 0 and 10")
        return v

    @field_validator("ats_score")
    @classmethod
    def validate_ats_score(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 <= v <= 100):
            raise ValueError("ats_score must be between 0 and 100")
        return v


class DeepResumeAnalysisRequest(BaseModel):
    """Used by POST /deep-resume-analysis."""
    jd_text: str = Field(..., min_length=100, max_length=15000)
    job_id: Optional[str] = None  # If provided, links analysis to existing job
```

**C2c.** Update `JobUpdate` -- add these two fields after `closed_reason`:

Find:
```python
    closed_reason: Optional[str] = Field(None, max_length=50)
    cover_letter: Optional[str] = None
```

Replace with:
```python
    closed_reason: Optional[str] = Field(None, max_length=50)
    fit_reasoning: Optional[str] = None
    salary_range: Optional[str] = Field(None, max_length=100)
    cover_letter: Optional[str] = None
```

---

## Task D -- Modify analyze_jd() in ai_service.py

**File:** `app/services/ai_service.py`

Find the entire `analyze_jd` function (lines 54-84). Replace with:

```python
async def analyze_jd(jd_text: str, profile: dict[str, Any]) -> dict | None:
    level = profile.get("experience_level", "Mid")
    level_hint = LEVEL_CONTEXT.get(level, LEVEL_CONTEXT["Mid"])

    prompt = f"""You are an expert career coach and ATS resume analyst.

EVALUATION CONTEXT: {level_hint}

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

JOB DESCRIPTION:
{jd_text}

Return ONLY valid JSON (no markdown, no backticks):
{{
  "b2c_check": true,
  "b2c_reason": "...",
  "ats_score": 75,
  "fit_score": 7.5,
  "fit_reasoning": "2-3 sentence explanation of why this score was given, referencing specific skill matches and gaps",
  "salary_range": "15-25 LPA" or "Not mentioned in JD",
  "keywords_matched": ["keyword1", "keyword2"],
  "keywords_missing": ["keyword3"],
  "resume_suggestions": [
    "Add X metric from Y project to demonstrate Z",
    "Reframe A experience to highlight B skill"
  ],
  "customize_recommendation": "Send master resume" or "Make 2-3 tweaks: ..." or "Needs deep customization",
  "cover_letter_draft": "Full 200-250 word cover letter. End with:\\n\\n[CANDIDATE_NAME]\\n[CANDIDATE_PHONE]\\n[CANDIDATE_LINKEDIN]",
  "interview_angle": "Key story to prepare...",
  "company_name": "extracted from JD",
  "role_title": "extracted from JD"
}}

IMPORTANT for cover_letter_draft:
- Write a complete, compelling cover letter (200-250 words)
- Reference specific skills from the candidate profile that match the JD
- End with the exact signature block: [CANDIDATE_NAME], [CANDIDATE_PHONE], [CANDIDATE_LINKEDIN] on separate lines
- Do NOT invent contact details. Use the placeholders exactly as shown."""

    result = await call_claude(prompt, max_tokens=4000)
    return parse_json_response(result)
```

**Key changes from existing:**
1. Added `fit_reasoning` field to JSON output
2. Added `salary_range` field
3. Added `resume_suggestions` array
4. Changed `cover_letter_draft` from "120-word draft" to "200-250 word full cover letter" with signature placeholders
5. Increased `max_tokens` from 2000 to 4000
6. Added IMPORTANT section about signature placeholders

### D2. Add new deep_resume_analysis() function

Insert this AFTER the `analyze_jd()` function (before `extract_profile()`):

```python
async def deep_resume_analysis(jd_text: str, resume_text: str, profile: dict[str, Any]) -> dict | None:
    """Deep analysis comparing resume against JD with specific rewrite suggestions."""
    level = profile.get("experience_level", "Mid")
    level_hint = LEVEL_CONTEXT.get(level, LEVEL_CONTEXT["Mid"])

    prompt = f"""You are an expert ATS resume analyst and career coach.

EVALUATION CONTEXT: {level_hint}

CANDIDATE RESUME:
{resume_text[:8000]}

JOB DESCRIPTION:
{jd_text}

Perform a deep analysis of how well this resume matches the JD. Return ONLY valid JSON:
{{
  "overall_match_score": 75,
  "section_scores": {{
    "skills_match": 80,
    "experience_relevance": 70,
    "education_fit": 60,
    "keywords_coverage": 75
  }},
  "ats_pass_likelihood": "High" or "Medium" or "Low",
  "critical_gaps": [
    "Missing X certification that is listed as required",
    "No mention of Y technology stack"
  ],
  "rewrite_suggestions": [
    {{
      "section": "Experience - Company ABC",
      "current": "Managed team of engineers",
      "suggested": "Led cross-functional team of 12 engineers, delivering 3 product launches that increased revenue by 40%",
      "reason": "JD emphasizes leadership impact and metrics"
    }}
  ],
  "keywords_to_add": ["keyword1", "keyword2"],
  "keywords_present": ["keyword3", "keyword4"],
  "recommended_format_changes": [
    "Move skills section above experience for this role",
    "Add a summary section highlighting X and Y"
  ],
  "executive_summary": "3-4 sentence overview of the resume-JD fit"
}}"""

    result = await call_claude(prompt, max_tokens=4000)
    return parse_json_response(result)
```

---

## Task E -- Refactor /analyze-jd Endpoint + New /save-from-analysis

**File:** `app/routers/jobs.py`

### E1. Add import for Settings

Find:
```python
from app.services.ai_service import analyze_jd, call_claude
```

Replace with:
```python
from app.config import get_settings
from app.services.ai_service import analyze_jd, call_claude, deep_resume_analysis
```

### E2. Add import for new schemas

Find:
```python
from app.schemas.jobs import AddNoteRequest, JDAnalyzeRequest, JobCreate, JobOut, JobUpdate, NoteEntry, PaginatedResponse
```

Replace with:
```python
from app.schemas.jobs import (
    AddNoteRequest,
    DeepResumeAnalysisRequest,
    JDAnalyzeRequest,
    JobCreate,
    JobOut,
    JobUpdate,
    NoteEntry,
    PaginatedResponse,
    SaveFromAnalysisRequest,
)
```

### E3. Replace the entire /analyze-jd endpoint

Find the entire `analyze_jd_endpoint` function (lines 285-359). Replace with:

```python
@router.post("/analyze-jd")
async def analyze_jd_endpoint(
    payload: JDAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Analyze a JD against the user's profile. Returns analysis only -- does NOT create a Job."""
    if not (100 <= len(payload.jd_text) <= 15000):
        raise HTTPException(status_code=400, detail="jd_text must be between 100 and 15000 characters")

    prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = prof_res.scalar_one_or_none()
    profile_dict: dict[str, Any] = {}
    if profile is not None:
        profile_dict = {
            "full_name": profile.full_name,
            "positioning_statement": profile.positioning_statement,
            "target_roles": profile.target_roles,
            "core_skills": profile.core_skills,
            "tools_platforms": profile.tools_platforms,
            "industries": profile.industries,
            "experience_level": profile.experience_level,
            "years_of_experience": profile.years_of_experience,
        }

    analysis = await analyze_jd(payload.jd_text, profile_dict)
    if analysis is None:
        raise HTTPException(status_code=503, detail="AI analysis temporarily unavailable")

    # Replace cover letter signature placeholders with real values from Settings
    settings = get_settings()
    cover_letter = analysis.get("cover_letter_draft", "")
    if cover_letter:
        candidate_name = profile.full_name if profile and profile.full_name else "Your Name"
        cover_letter = cover_letter.replace("[CANDIDATE_NAME]", candidate_name)
        cover_letter = cover_letter.replace("[CANDIDATE_PHONE]", settings.owner_phone or "")
        cover_letter = cover_letter.replace("[CANDIDATE_LINKEDIN]", settings.owner_linkedin_url or "")
        analysis["cover_letter_draft"] = cover_letter

    return {
        "analysis": analysis,
        "company_name": analysis.get("company_name", "Unknown Company"),
        "role_title": analysis.get("role_title", "Unknown Role"),
        "jd_url": payload.jd_url,
    }
```

**Key changes:** Removed ALL Job creation/update logic. The endpoint now ONLY returns analysis. Job creation is handled by the new `/save-from-analysis` endpoint.

### E4. Add /save-from-analysis endpoint

Insert this NEW endpoint AFTER `/analyze-jd` and BEFORE `/search` (i.e., in the FIXED-PATH section). Find:

```python
@router.get("/search")
async def global_search(
```

Insert BEFORE it:

```python
@router.post("/save-from-analysis", response_model=JobOut, status_code=201)
async def save_from_analysis(
    payload: SaveFromAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Save a Job from JD analysis results. Deduplicates by company+role."""
    company_name = payload.company_name
    role_title = payload.role_title

    existing = await db.execute(
        select(Job).where(
            Job.user_id == current_user.id,
            func.lower(Job.company_name) == func.lower(company_name),
            func.lower(Job.role_title) == func.lower(role_title),
            Job.is_deleted.is_(False),
        )
    )
    existing_job = existing.scalar_one_or_none()

    if existing_job:
        existing_job.fit_score = payload.fit_score
        existing_job.ats_score = payload.ats_score
        existing_job.fit_reasoning = payload.fit_reasoning
        existing_job.salary_range = payload.salary_range
        existing_job.jd_text = payload.jd_text
        existing_job.jd_url = payload.jd_url
        existing_job.keywords_matched = payload.keywords_matched
        existing_job.keywords_missing = payload.keywords_missing
        existing_job.ai_analysis = payload.ai_analysis
        existing_job.cover_letter = payload.cover_letter
        existing_job.source_portal = payload.source_portal or "JD Analysis"
        job = existing_job
    else:
        job = Job(
            user_id=current_user.id,
            company_name=company_name,
            role_title=role_title,
            jd_text=payload.jd_text,
            jd_url=payload.jd_url,
            status="Tracking",
            fit_score=payload.fit_score,
            ats_score=payload.ats_score,
            fit_reasoning=payload.fit_reasoning,
            salary_range=payload.salary_range,
            keywords_matched=payload.keywords_matched,
            keywords_missing=payload.keywords_missing,
            ai_analysis=payload.ai_analysis,
            cover_letter=payload.cover_letter,
            source_portal=payload.source_portal or "JD Analysis",
        )
        db.add(job)

    await db.commit()
    await db.refresh(job)

    await log_activity(db, current_user.id, "job_analyzed", f"Saved JD analysis: {company_name} - {role_title}", related_job_id=job.id)
    await db.commit()

    return JobOut.model_validate(job)


```

---

## Task F -- New POST /deep-resume-analysis Endpoint

**File:** `app/routers/jobs.py`

Insert this endpoint AFTER `/save-from-analysis` and BEFORE `/search`. Find:

```python
@router.get("/search")
async def global_search(
```

Insert BEFORE it:

```python
@router.post("/deep-resume-analysis")
async def deep_resume_analysis_endpoint(
    payload: DeepResumeAnalysisRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Deep resume-vs-JD analysis. Requires raw_resume_text in ProfileDNA."""
    if not (100 <= len(payload.jd_text) <= 15000):
        raise HTTPException(status_code=400, detail="jd_text must be between 100 and 15000 characters")

    prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == current_user.id))
    profile = prof_res.scalar_one_or_none()
    if profile is None or not profile.raw_resume_text:
        raise HTTPException(status_code=400, detail="No resume text found. Upload your resume to ProfileDNA first.")

    profile_dict: dict[str, Any] = {
        "full_name": profile.full_name,
        "positioning_statement": profile.positioning_statement,
        "target_roles": profile.target_roles,
        "core_skills": profile.core_skills,
        "tools_platforms": profile.tools_platforms,
        "industries": profile.industries,
        "experience_level": profile.experience_level,
        "years_of_experience": profile.years_of_experience,
    }

    analysis = await deep_resume_analysis(payload.jd_text, profile.raw_resume_text, profile_dict)
    if analysis is None:
        raise HTTPException(status_code=503, detail="AI analysis temporarily unavailable")

    # If job_id provided, store analysis on the job
    if payload.job_id:
        job = await db.get(Job, payload.job_id)
        if job and job.user_id == current_user.id and not job.is_deleted:
            existing_ai = job.ai_analysis or {}
            existing_ai["deep_resume_analysis"] = analysis
            job.ai_analysis = existing_ai
            flag_modified(job, "ai_analysis")
            await db.commit()

    return {"analysis": analysis, "job_id": payload.job_id}


```

---

## Task G -- Fuzzy Company Search + Quick-Create

### G1. Add CompanyQuickCreate schema

**File:** `app/schemas/companies.py`

Find:
```python
class CompanyUpdate(BaseModel):
```

Insert BEFORE it:
```python
class CompanyQuickCreate(BaseModel):
    """Minimal company creation from JD analysis flow."""
    name: str = Field(..., max_length=255)
    lane: int = Field(2, ge=1, le=3)
    sector: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)


```

### G2. Update company router imports

**File:** `app/routers/companies.py`

Find:
```python
from app.schemas.companies import CompanyCreate, CompanyOut, CompanySearchResult, CompanyUpdate
```

Replace with:
```python
from sqlalchemy import text

from app.schemas.companies import CompanyCreate, CompanyOut, CompanyQuickCreate, CompanySearchResult, CompanyUpdate
```

### G3. Update search endpoint to use pg_trgm

Find the entire `search_companies` function (lines 52-68). Replace with:

```python
@router.get("/search", response_model=list[CompanySearchResult])
async def search_companies(
    q: str = Query(..., min_length=2),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Search companies by name using fuzzy matching (pg_trgm)."""
    result = await db.execute(
        select(Company)
        .where(
            Company.user_id == current_user.id,
            func.similarity(Company.name, q) > 0.3,
        )
        .order_by(func.similarity(Company.name, q).desc())
        .limit(5)
    )
    companies = result.scalars().all()
    return [CompanySearchResult.model_validate(c) for c in companies]
```

### G4. Add quick-create endpoint

Insert this AFTER the `/search` endpoint and BEFORE `/{company_id}`. Find:

```python
@router.get("/{company_id}", response_model=CompanyOut)
async def get_company(
```

Insert BEFORE it:

```python
@router.post("/quick-create", response_model=CompanyOut, status_code=201)
async def quick_create_company(
    payload: CompanyQuickCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Quick-create a company with minimal fields. Returns existing if duplicate."""
    existing = await db.execute(
        select(Company).where(
            Company.user_id == current_user.id,
            func.lower(Company.name) == func.lower(payload.name),
        )
    )
    existing_company = existing.scalar_one_or_none()
    if existing_company:
        return CompanyOut.model_validate(existing_company)

    company = Company(user_id=current_user.id, **payload.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return CompanyOut.model_validate(company)


```

**Note:** Unlike `POST /` which returns 409 on duplicate, `/quick-create` returns the existing company (200). This is intentional for the JD analysis flow where the frontend auto-creates companies.

---

## Task H -- Auto-note on Status Change in PATCH Handler

**File:** `app/routers/jobs.py`

Find this block in the `update_job` function:

```python
    # Default closed_reason when status changes to 'Closed'
    if update_data.get("status") == "Closed" and job.closed_reason is None:
        job.closed_reason = "No Response"

    await db.commit()
    await db.refresh(job)
```

Replace with:

```python
    # Default closed_reason when status changes to 'Closed'
    if update_data.get("status") == "Closed" and job.closed_reason is None:
        job.closed_reason = "No Response"

    # Auto-note on status change
    new_status = update_data.get("status")
    if new_status and new_status != old_status:
        existing_notes = job.notes if job.notes is not None else []
        existing_notes.append({
            "text": f"Status changed: {old_status} -> {new_status}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "type": "status_change",
        })
        job.notes = existing_notes
        flag_modified(job, "notes")

    await db.commit()
    await db.refresh(job)
```

---

## Task I -- Update Telegram /jd Command

**File:** `app/routers/telegram.py`

Find:
```python
    if command == "/jd":
        if len(arg) < 100:
            await send_telegram_message(chat_id, "Please send a full JD (at least 100 characters).")
            return {"ok": True}
        req = JDAnalyzeRequest(jd_text=arg, jd_url=None)
        # Call internal endpoint logic directly
        from app.dependencies import get_current_user as _gc

        # Here we bypass dependency; pass current user and db into helper
        analysis = await analyze_jd_endpoint(req, db=db, current_user=user)  # type: ignore[arg-type]
        await send_telegram_message(chat_id, f"ATS score: {analysis['analysis'].get('ats_score')}\nFit: {analysis['analysis'].get('fit_score')}")
        return {"ok": True}
```

Replace with:
```python
    if command == "/jd":
        if len(arg) < 100:
            await send_telegram_message(chat_id, "Please send a full JD (at least 100 characters).")
            return {"ok": True}
        req = JDAnalyzeRequest(jd_text=arg, jd_url=None)
        result = await analyze_jd_endpoint(req, db=db, current_user=user)  # type: ignore[arg-type]
        a = result.get("analysis", {})
        lines = [
            f"Company: {result.get('company_name', 'Unknown')}",
            f"Role: {result.get('role_title', 'Unknown')}",
            f"ATS Score: {a.get('ats_score', 'N/A')}",
            f"Fit Score: {a.get('fit_score', 'N/A')}",
            "",
            f"Fit Reasoning: {a.get('fit_reasoning', 'N/A')}",
            "",
            f"Salary Range: {a.get('salary_range', 'Not specified')}",
            "",
            "Resume Suggestions:",
        ]
        for s in a.get("resume_suggestions", []):
            lines.append(f"  - {s}")
        lines.append("")
        lines.append(f"Recommendation: {a.get('customize_recommendation', 'N/A')}")
        msg = "\n".join(lines)
        # Telegram limit: 4096 chars
        if len(msg) > 4000:
            msg = msg[:4000] + "\n...(truncated)"
        await send_telegram_message(chat_id, msg)
        return {"ok": True}
```

**Note:** The old import `from app.dependencies import get_current_user as _gc` was unused -- remove it. The `analyze_jd_endpoint` import at line 13 remains the same since the function name hasn't changed, only its behavior.

---

## Task J -- Auto-Ghost Scheduled Task

### J1. Create task file

**Create file:** `app/tasks/auto_ghost.py`

```python
"""Auto-ghost task -- closes stale Applied jobs after 30 days of no updates."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.models.job import Job
from app.models.user import User
from app.services.telegram_service import send_telegram_message
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)


async def auto_ghost_task() -> None:
    """
    Runs at 2:55 AM UTC (8:25 AM IST) Mon-Sat.
    Finds jobs in 'Applied' status with no updates for 30+ days.
    Sets status='Closed', closed_reason='Ghosted', adds auto-note.
    Sends Telegram summary.
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id

    async with get_task_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        result = await db.execute(
            select(Job).where(
                Job.status == "Applied",
                Job.updated_at < cutoff,
                Job.is_deleted.is_(False),
            )
        )
        stale_jobs = result.scalars().all()

        if not stale_jobs:
            logger.info("Auto-ghost: no stale Applied jobs found")
            return

        ghosted = []
        for job in stale_jobs:
            days_stale = (datetime.now(timezone.utc) - job.updated_at).days
            job.status = "Closed"
            job.closed_reason = "Ghosted"

            # Add auto-note
            existing_notes = job.notes if job.notes is not None else []
            existing_notes.append({
                "text": f"Auto-closed: no response after {days_stale} days",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "type": "auto_ghost",
            })
            job.notes = existing_notes
            flag_modified(job, "notes")

            ghosted.append(f"  - {job.company_name} - {job.role_title} ({days_stale}d)")

        await db.commit()
        logger.info(f"Auto-ghost: closed {len(ghosted)} stale jobs")

        if chat_id and ghosted:
            msg = f"Auto-ghost: {len(ghosted)} jobs closed (no response 30+ days):\n"
            msg += "\n".join(ghosted[:20])  # Cap at 20 to avoid message limit
            if len(ghosted) > 20:
                msg += f"\n  ...and {len(ghosted) - 20} more"
            await send_telegram_message(chat_id, msg)
```

### J2. Register in scheduler

**File:** `app/scheduler.py`

Find:
```python
    from app.tasks.weekly_review import weekly_review_task
```

Add after it:
```python
    from app.tasks.auto_ghost import auto_ghost_task
```

Find this block (the weekly_review add_job call):
```python
    # Sunday 9:00 AM IST = 3:30 AM UTC
    scheduler.add_job(
        weekly_review_task,
        CronTrigger(hour=3, minute=30, day_of_week="sun"),
        id="weekly_review",
        replace_existing=True,
        misfire_grace_time=300,
    )
```

Insert AFTER it:
```python

    # 8:25 AM IST = 2:55 AM UTC -- Mon-Sat
    scheduler.add_job(
        auto_ghost_task,
        CronTrigger(hour=2, minute=55, day_of_week="mon-sat"),
        id="auto_ghost",
        replace_existing=True,
        misfire_grace_time=300,
    )
```

Find the logger.info line:
```python
    logger.info(
        "Scheduler jobs registered: "
        "morning (03:00 UTC), midday (08:30 UTC), "
        "evening (13:00 UTC), linkedin (13:30 UTC), "
        "weekly (Sun 03:30 UTC)"
    )
```

Replace with:
```python
    logger.info(
        "Scheduler jobs registered: "
        "auto_ghost (02:55 UTC), morning (03:00 UTC), midday (08:30 UTC), "
        "evening (13:00 UTC), linkedin (13:30 UTC), "
        "weekly (Sun 03:30 UTC)"
    )
```

### J3. Add test command in Telegram

**File:** `app/routers/telegram.py`

Find:
```python
    if command == "/test-review":
        from app.tasks.weekly_review import weekly_review_task
        await weekly_review_task()
        return {"ok": True}
```

Insert AFTER it:
```python
    if command == "/test-ghost":
        from app.tasks.auto_ghost import auto_ghost_task
        await auto_ghost_task()
        return {"ok": True}

```

---

## CRITICAL CONSTRAINTS -- DO NOT VIOLATE

1. **No hardcoded phone numbers or LinkedIn URLs.** Always read from `settings.owner_phone` and `settings.owner_linkedin_url`. The cover letter uses `[CANDIDATE_PHONE]` and `[CANDIDATE_LINKEDIN]` placeholders that get replaced in the endpoint, NOT in the AI service function.

2. **No em dashes.** Use `--` instead of special Unicode characters. This applies to docstrings, comments, migration descriptions, and all string literals.

3. **Route order matters.** All fixed-path routes (`/analyze-jd`, `/save-from-analysis`, `/deep-resume-analysis`, `/search`, `/pipeline`, `/stale`, `/followups`) MUST be declared BEFORE parametric routes (`/{job_id}`, `/{company_id}`). Same for companies: `/search` and `/quick-create` before `/{company_id}`.

4. **`job_id: str` not UUID.** All existing endpoints use `job_id: str`. Follow this convention. Do NOT change to `job_id: UUID`.

5. **`flag_modified()` for JSONB.** After any in-place mutation of `job.notes` or `job.ai_analysis`, call `flag_modified(job, "field_name")`. SQLAlchemy does not detect in-place JSONB changes.

6. **`datetime.now(timezone.utc)` only.** Never `datetime.utcnow()`. Never `datetime.now()` without timezone.

7. **Scheduler times in UTC.** Railway runs in UTC. IST = UTC + 5:30. The auto-ghost task runs at 2:55 AM UTC = 8:25 AM IST.

8. **Lazy imports in scheduler.** The `register_jobs()` function uses lazy imports to avoid circular dependencies. Follow this pattern for `auto_ghost_task`.

9. **Do NOT modify** these files: `app/models/base.py`, `app/database.py`, `app/main.py`, `app/dependencies.py`, `app/models/user.py`, any existing migration files, any existing task files in `app/tasks/`.

10. **Migration chain.** The new migration's `down_revision` MUST be `'c3d4e5f6a7b8'`. Verify by checking `alembic/versions/c3d4e5f6a7b8_jobs_status_overhaul_and_notes_jsonb.py`.

11. **Backwards compatibility.** The `/analyze-jd` endpoint's return shape changes (no more `job_id` in response). The Telegram `/jd` command is updated to handle this. No other callers exist.

12. **`pg_trgm` function import.** SQLAlchemy's `func.similarity()` works automatically when pg_trgm extension is enabled. No special import needed beyond `from sqlalchemy import func`.

---

## EXECUTION ORDER

Run tasks in this order to avoid import/dependency errors:
1. **A** (config) -- no dependencies
2. **B** (migration) -- run `alembic upgrade head` after
3. **C** (model + schemas) -- depends on migration being applied
4. **D** (ai_service) -- no dependencies on other tasks
5. **E** (analyze-jd refactor + save-from-analysis) -- depends on C, D
6. **F** (deep-resume-analysis) -- depends on C, D
7. **G** (company search + quick-create) -- depends on B (pg_trgm)
8. **H** (auto-note on status change) -- depends on C
9. **I** (telegram /jd) -- depends on E
10. **J** (auto-ghost) -- depends on C

---

## SUMMARY OF FILES

| Action | File |
|---|---|
| MODIFY | `app/config.py` |
| CREATE | `alembic/versions/d4e5f6a7b8c9_jd_analyzer_redesign_phase_a.py` |
| MODIFY | `app/models/job.py` |
| MODIFY | `app/schemas/jobs.py` |
| MODIFY | `app/schemas/companies.py` |
| MODIFY | `app/services/ai_service.py` |
| MODIFY | `app/routers/jobs.py` |
| MODIFY | `app/routers/companies.py` |
| MODIFY | `app/routers/telegram.py` |
| CREATE | `app/tasks/auto_ghost.py` |
| MODIFY | `app/scheduler.py` |

