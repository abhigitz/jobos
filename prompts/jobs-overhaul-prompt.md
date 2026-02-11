# Jobs System Overhaul — Claude Code Prompt

You are working on **JobOS**, a FastAPI + SQLAlchemy async + PostgreSQL backend. The codebase uses `datetime.now(timezone.utc)` everywhere — never use `datetime.utcnow()` (there are 2 existing bugs at lines 123 and 139 of `app/routers/jobs.py` that use `datetime.utcnow()` — fix those too).

---

## Files you MUST read before writing any code

| File | What to learn |
|---|---|
| `app/models/job.py` | Full Job model: 24 data columns, CHECK constraint named `ck_jobs_status_valid`, notes is `Text`, no `application_channel` or `closed_reason` columns |
| `app/routers/jobs.py` | ALL 14 endpoints. Focus on: hardcoded status strings in `/pipeline` (line 153: `inactive_statuses = {"Rejected", "Withdrawn", "Ghosted"}`), `/stale` (line 204: `Job.status == "Applied"`), `/followups` (line 237: `Job.status == "Applied"`), `/analyze-jd` (line 342: `status="Analyzed"`), `/interview` (line 533: `if job.status in ("Applied", "Screening"): job.status = "Interview Scheduled"`), `/debrief` (line 591: `job.status = "Interview Done"`), `/{job_id}/followup` (lines 484-486: concatenates notes as TEXT strings — will break after JSONB conversion) |
| `app/schemas/jobs.py` | `JobCreate` (default status "Applied", 9 allowed values), `JobUpdate` (10 fields, 9 allowed status values), `JobOut` (only 10 of 24+ fields) |
| `app/models/company.py` | Company model — DO NOT modify this file |
| `app/routers/companies.py` | 6 endpoints. `GET /{company_id}` is at line 52 — new search route MUST come before it |
| `app/schemas/companies.py` | `CompanyCreate`, `CompanyUpdate`, `CompanyOut` — add `CompanySearchResult` here |
| `alembic/versions/b2c3d4e5f6a7_add_email_verification_and_password_reset.py` | Latest migration — new migration's `down_revision` must be `'b2c3d4e5f6a7'` |
| `app/models/base.py` | `IDMixin`, `TimestampMixin` — understand inherited columns (id, created_at, updated_at) |

---

## Task A — ALEMBIC MIGRATION

Create file: `alembic/versions/c3d4e5f6a7b8_jobs_status_overhaul_and_notes_jsonb.py`

```python
"""Jobs status overhaul and notes JSONB conversion

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
```

`down_revision = 'b2c3d4e5f6a7'`

### upgrade() — execute in THIS EXACT ORDER:

**Step 1: Add new columns**
```python
op.add_column('jobs', sa.Column('application_channel', sa.String(50), nullable=True))
op.add_column('jobs', sa.Column('closed_reason', sa.String(50), nullable=True))
```

**Step 2: DROP the old CHECK constraint FIRST** — this frees the status column so data migration can use any values without constraint violations:
```python
op.drop_constraint('ck_jobs_status_valid', 'jobs', type_='check')
```

**Step 3: Migrate status data** — no `_temp` trick needed since the constraint is already gone:
```python
# Set closed_reason from old terminal statuses
op.execute("UPDATE jobs SET closed_reason = 'Rejected' WHERE status = 'Rejected'")
op.execute("UPDATE jobs SET closed_reason = 'Withdrawn' WHERE status = 'Withdrawn'")
op.execute("UPDATE jobs SET closed_reason = 'Ghosted' WHERE status = 'Ghosted'")

# Map old statuses to new statuses
op.execute("UPDATE jobs SET status = 'Closed' WHERE status IN ('Rejected', 'Withdrawn', 'Ghosted')")
op.execute("UPDATE jobs SET status = 'Tracking' WHERE status = 'Analyzed'")
op.execute("UPDATE jobs SET status = 'Applied' WHERE status = 'Screening'")
op.execute("UPDATE jobs SET status = 'Interview' WHERE status IN ('Interview Scheduled', 'Interview Done')")
```

**Step 4: Add new CHECK constraint**
```python
op.create_check_constraint(
    'ck_jobs_status_valid',
    'jobs',
    "status IN ('Tracking', 'Applied', 'Interview', 'Offer', 'Closed')"
)
```

**Step 5: Convert notes from Text to JSONB.** CRITICAL — PostgreSQL cannot implicitly cast Text to JSONB. You MUST use raw SQL via `op.execute()`. Do NOT use `op.alter_column()` — it won't handle the `USING` clause:
```python
op.execute("""
    ALTER TABLE jobs ALTER COLUMN notes TYPE JSONB USING
      CASE
        WHEN notes IS NULL THEN '[]'::jsonb
        WHEN notes = '' THEN '[]'::jsonb
        ELSE jsonb_build_array(jsonb_build_object('text', notes, 'created_at', now()::text))
      END
""")
op.execute("ALTER TABLE jobs ALTER COLUMN notes SET DEFAULT '[]'::jsonb")
```

### downgrade() — reverse everything in correct order:

**Step 1:** Remove notes default, convert JSONB back to Text:
```python
op.execute("ALTER TABLE jobs ALTER COLUMN notes DROP DEFAULT")
op.execute("""
    ALTER TABLE jobs ALTER COLUMN notes TYPE TEXT USING
      CASE
        WHEN notes IS NULL THEN NULL
        WHEN jsonb_array_length(notes) = 0 THEN NULL
        ELSE notes->0->>'text'
      END
""")
```

**Step 2:** Drop new CHECK, reverse status migration, add back old CHECK:
```python
op.drop_constraint('ck_jobs_status_valid', 'jobs', type_='check')
```

```python
# Reverse status migration
op.execute("UPDATE jobs SET status = 'Analyzed' WHERE status = 'Tracking'")
op.execute("UPDATE jobs SET status = 'Interview Scheduled' WHERE status = 'Interview'")
# Use closed_reason to restore original terminal statuses where possible
op.execute("UPDATE jobs SET status = closed_reason WHERE status = 'Closed' AND closed_reason IN ('Rejected', 'Withdrawn', 'Ghosted')")
op.execute("UPDATE jobs SET status = 'Rejected' WHERE status = 'Closed'")
```

```python
op.create_check_constraint(
    'ck_jobs_status_valid',
    'jobs',
    "status IN ('Analyzed', 'Applied', 'Screening', 'Interview Scheduled', 'Interview Done', 'Offer', 'Rejected', 'Withdrawn', 'Ghosted')"
)
```

**Step 3:** Drop new columns:
```python
op.drop_column('jobs', 'closed_reason')
op.drop_column('jobs', 'application_channel')
```

---

## Task B — MODEL CHANGES (`app/models/job.py`)

**B1.** Update the CHECK constraint values:
```python
__table_args__ = (
    CheckConstraint(
        "status IN ('Tracking', 'Applied', 'Interview', 'Offer', 'Closed')",
        name="ck_jobs_status_valid",
    ),
)
```

**B2.** Change `status` default from `"Applied"` to `"Tracking"`:
```python
status: Mapped[str] = mapped_column(String(50), default="Tracking")
```

**B3.** Add two new columns (after `referral_contact`, before `keywords_matched`):
```python
application_channel: Mapped[str | None] = mapped_column(String(50))
closed_reason: Mapped[str | None] = mapped_column(String(50))
```

**B4.** Change `notes` from Text to JSONB. `JSONB` is already imported from `sqlalchemy.dialects.postgresql`:
```python
notes: Mapped[list | None] = mapped_column(JSONB, server_default='[]', default=list)
```
Remove `Text` from the SQLAlchemy import line if no other column uses it... but `jd_text`, `cover_letter`, `prep_notes`, `interview_feedback` all use `Text`, so keep the import.

---

## Task C — SCHEMA CHANGES (`app/schemas/jobs.py`)

**C1. Add NoteEntry and AddNoteRequest** (at top of file, after JDAnalyzeRequest):
```python
class NoteEntry(BaseModel):
    text: str
    created_at: str

class AddNoteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
```

**C2. Update JobCreate:**
- Change default status from `"Applied"` to `"Tracking"`
- Update allowed status values to: `{"Tracking", "Applied", "Interview", "Offer", "Closed"}`
- Change notes type from `Optional[str]` to `Optional[list[dict]]`

**C3. Update JobUpdate:**

Add these fields (keep all existing ones):
```python
company_name: Optional[str] = Field(None, max_length=255)
role_title: Optional[str] = Field(None, max_length=255)
referral_contact: Optional[str] = Field(None, max_length=255)
application_channel: Optional[str] = Field(None, max_length=50)
closed_reason: Optional[str] = Field(None, max_length=50)
cover_letter: Optional[str] = None
source_portal: Optional[str] = Field(None, max_length=100)
jd_url: Optional[str] = Field(None, max_length=1000)
```

Change `notes` type from `Optional[str]` to `Optional[list[dict]]`.

Update status validator — allowed values: `{"Tracking", "Applied", "Interview", "Offer", "Closed"}`.

Add a `model_validator(mode='after')` to handle closed_reason defaulting:
```python
from pydantic import model_validator

@model_validator(mode='after')
def default_closed_reason(self):
    if self.status == 'Closed' and self.closed_reason is None:
        self.closed_reason = 'No Response'
    return self
```

**C4. Expand JobOut from 10 fields to ALL model columns:**
```python
class JobOut(BaseModel):
    id: UUID
    company_name: str
    role_title: str
    jd_text: Optional[str] = None
    jd_url: Optional[str] = None
    source_portal: Optional[str] = None
    fit_score: Optional[float] = None
    ats_score: Optional[float] = None
    status: str
    resume_version: Optional[str] = None
    apply_type: Optional[str] = None
    cover_letter: Optional[str] = None
    referral_contact: Optional[str] = None
    keywords_matched: Optional[list[str]] = None
    keywords_missing: Optional[list[str]] = None
    ai_analysis: Optional[dict] = None
    applied_date: Optional[date] = None
    interview_date: Optional[datetime] = None
    interview_type: Optional[str] = None
    interviewer_name: Optional[str] = None
    interviewer_linkedin: Optional[str] = None
    prep_notes: Optional[str] = None
    interview_feedback: Optional[str] = None
    is_deleted: bool = False
    notes: Optional[list[dict]] = None
    application_channel: Optional[str] = None
    closed_reason: Optional[str] = None
    last_followup_date: Optional[date] = None
    followup_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```
Note: `updated_at` comes from `TimestampMixin` — include it.

**C5. Update the import in `app/routers/jobs.py`** to include the new schemas:
Add `AddNoteRequest` and `NoteEntry` to the import from `app.schemas.jobs`.

---

## Task D — ENDPOINT CHANGES (`app/routers/jobs.py`)

**D1. Fix `datetime.utcnow()` bugs** (2 occurrences):
- Line 123: `applied_date=data.get("applied_date") or datetime.utcnow().date()` → change to `datetime.now(timezone.utc).date()`
- Line 139: `today = datetime.utcnow().date()` → change to `today = datetime.now(timezone.utc).date()`

**D2. POST /analyze-jd** — line 342: Change `status="Analyzed"` to `status="Tracking"`.

**D3. GET /pipeline** — update hardcoded status strings:
- Line 153: Change `inactive_statuses = {"Rejected", "Withdrawn", "Ghosted"}` to `inactive_statuses = {"Closed"}`
- Line 174: Change `if job.status == "Applied"` to `if job.status in ("Applied", "Tracking")` (these are the statuses that can go stale)

**D4. GET /stale** — line 204: Change `Job.status == "Applied"` to `Job.status.in_(["Applied", "Tracking"])`. Also update the suggested_action at line 222: change `"mark as Ghosted"` to `"mark as Closed"`.

**D5. GET /followups** — line 237: Change `Job.status == "Applied"` to `Job.status.in_(["Applied", "Tracking"])`. Also line 273: change `"mark as Ghosted"` to `"mark as Closed"`.

**D6. POST /{job_id}/interview** — line 533: Change `if job.status in ("Applied", "Screening"):` to `if job.status in ("Applied", "Tracking"):`. Change `job.status = "Interview Scheduled"` to `job.status = "Interview"`.

**D7. POST /{job_id}/debrief** — line 591: Change `job.status = "Interview Done"` to `job.status = "Interview"` (it stays in Interview status — a completed interview doesn't change the pipeline status since there's no separate "Interview Done" state now).

**D8. PATCH /{job_id}/followup** — lines 483-486 currently concatenate notes as text strings. After JSONB conversion, change to:
```python
if payload.notes:
    existing = job.notes if job.notes is not None else []
    existing.append({
        "text": f"[Follow-up {date.today()}] {payload.notes}",
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    job.notes = existing
    flag_modified(job, "notes")
```
The `flag_modified` import goes at the top of the file (see D10).

**D9. PATCH /{job_id}** — after the `setattr` loop (line 443), add handling for closed_reason default:
```python
update_data = payload.model_dump(exclude_unset=True)
for field, value in update_data.items():
    setattr(job, field, value)

# Default closed_reason when status changes to 'Closed'
if update_data.get("status") == "Closed" and job.closed_reason is None:
    job.closed_reason = "No Response"
```

**D10. Add POST /{job_id}/notes endpoint.** Place it after the existing `/{job_id}/followup` route but before `/{job_id}/interview`. Note: all existing `job_id` parameters in this file use `str` type (e.g. `get_job(job_id: str, ...)`, `delete_job(job_id: str, ...)`). Follow the same pattern:

```python
@router.post("/{job_id}/notes")
async def add_note(
    job_id: str,
    payload: AddNoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Add a note to a job's notes JSONB array."""
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id or job.is_deleted:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = job.notes if job.notes is not None else []
    existing.append({
        "text": payload.text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    job.notes = existing
    flag_modified(job, "notes")

    await db.commit()
    await db.refresh(job)
    return {"notes": job.notes}
```

Add `from sqlalchemy.orm.attributes import flag_modified` to the imports at the top of `app/routers/jobs.py`.

**D11. In POST /create_job (line 116):** Change `status=data.get("status") or "Applied"` to `status=data.get("status") or "Tracking"`.

---

## Task E — COMPANY SEARCH (`app/routers/companies.py` and `app/schemas/companies.py`)

**E1. Add CompanySearchResult schema** to `app/schemas/companies.py`:
```python
class CompanySearchResult(BaseModel):
    id: UUID
    name: str
    lane: int
    sector: Optional[str] = None
    hq_city: Optional[str] = None

    class Config:
        from_attributes = True
```

**E2. Add GET /search endpoint** to `app/routers/companies.py`. **CRITICAL: This route MUST be declared BEFORE `GET /{company_id}` (currently at line 52).** Place it between `POST /` (line 29) and `GET /{company_id}` (line 52). If you put it after, FastAPI will try to parse "search" as a UUID and return 422.

```python
from fastapi import Query  # add to existing imports

@router.get("/search", response_model=list[CompanySearchResult])
async def search_companies(
    q: str = Query(..., min_length=2),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Search companies by name. Returns top 5 matches."""
    result = await db.execute(
        select(Company)
        .where(
            Company.user_id == current_user.id,
            Company.name.ilike(f"%{q}%"),
        )
        .limit(5)
    )
    companies = result.scalars().all()
    return [CompanySearchResult.model_validate(c) for c in companies]
```

Update the import at the top of `app/routers/companies.py` to include `CompanySearchResult`:
```python
from app.schemas.companies import CompanyCreate, CompanyOut, CompanySearchResult, CompanyUpdate
```

Add `Query` to the FastAPI import:
```python
from fastapi import APIRouter, Depends, HTTPException, Query
```

---

## CRITICAL IMPLEMENTATION DETAILS

1. **Timezone**: Always `datetime.now(timezone.utc)`. Fix the 2 existing `datetime.utcnow()` bugs.
2. **JSONB mutation detection**: Use `flag_modified(job, "notes")` from `sqlalchemy.orm.attributes` after any in-place JSONB mutation. SQLAlchemy will NOT detect changes to JSONB arrays otherwise and will silently skip the UPDATE.
3. **Migration order matters**: add columns → DROP old constraint → migrate data → add new constraint → convert notes type. The constraint must be dropped BEFORE data migration so status values can be freely changed.
4. **Text → JSONB conversion**: MUST use raw SQL with `USING` clause via `op.execute()`. Using `op.alter_column()` does NOT support `USING`.
5. **Company search route order**: `GET /search` MUST be declared BEFORE `GET /{company_id}` in the router file. FastAPI matches routes in declaration order.
6. **Company search MUST filter by `user_id`** — this is a multi-user system.
7. **The `flag_modified` import** goes at the top of `app/routers/jobs.py`, not inline.
8. **`job_id` type**: All existing endpoints use `job_id: str`. Follow the same pattern for the new notes endpoint.

---

## WHAT NOT TO CHANGE

- Do NOT modify `app/services/ai_service.py` or the AI analysis prompt
- Do NOT modify `app/auth/` or `app/dependencies.py`
- Do NOT modify `app/models/company.py`
- Do NOT modify `app/models/base.py`
- Do NOT modify `app/database.py`
- Do NOT add a `company_id` FK to the jobs table
- Do NOT create any new files except the Alembic migration
- Do NOT delete any existing endpoints
- Do NOT modify the Interview model (`app/models/interview.py`)

---

## Files to modify (summary)

| File | Changes |
|---|---|
| `alembic/versions/c3d4e5f6a7b8_jobs_status_overhaul_and_notes_jsonb.py` | **NEW FILE** — migration with upgrade() and downgrade() |
| `app/models/job.py` | Update CHECK constraint to 5 new values, change status default to "Tracking", add `application_channel` and `closed_reason` columns, change notes from Text to JSONB |
| `app/schemas/jobs.py` | Add `NoteEntry` + `AddNoteRequest`, expand `JobOut` to all columns, expand `JobUpdate` with new fields + model_validator, update `JobCreate` default + allowed values, change notes type to `list[dict]` |
| `app/routers/jobs.py` | Fix 2 `utcnow()` bugs, update all hardcoded status strings in pipeline/stale/followups/interview/debrief, change analyze-jd to "Tracking", change create_job default to "Tracking", add closed_reason defaulting in PATCH, convert followup notes to JSONB append, add `POST /{job_id}/notes` endpoint, add `flag_modified` import |
| `app/schemas/companies.py` | Add `CompanySearchResult` schema |
| `app/routers/companies.py` | Add `GET /search` endpoint BEFORE `/{company_id}`, add `Query` import, add `CompanySearchResult` import |

