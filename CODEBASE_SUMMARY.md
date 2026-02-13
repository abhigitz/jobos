# JobOS Codebase Summary

## Crisp Codebase Overview

**JobOS** is a Python FastAPI backend for a job-search and career-management platform. It provides:

- **Auth**: JWT-based auth, email verification, password reset, optional n8n secret for automation
- **Core entities**: Users, Profile DNA, Companies, Jobs, Contacts, Interviews, Resumes
- **AI-powered features**: JD analysis, resume extraction, company deep-dives, content generation, interview prep
- **Scheduled tasks** (APScheduler): Morning briefing, midday check, evening check-in, LinkedIn content, weekly review, job scout, auto-ghost, DB backup
- **Integrations**: Telegram bot (webhook), Serper/Adzuna for job search, Anthropic Claude for AI
- **Content Studio**: Topic generation, post drafts, engagement tracking, story prompts

**Stack**: FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, Pydantic, Alembic

**Structure**:
```
app/
├── main.py           # FastAPI app, lifespan, middleware, routers
├── config.py         # Pydantic Settings (env vars)
├── database.py       # Async engine, session factory
├── dependencies.py   # Auth, rate limiting
├── models/           # SQLAlchemy models (User, Job, Company, etc.)
├── schemas/          # Pydantic request/response models
├── routers/          # API endpoints (auth, jobs, resume, scout, etc.)
├── services/         # AI, JD extractor, scout, telegram, company research
├── tasks/            # Scheduler tasks (briefing, backup, job_scout, etc.)
└── auth/             # JWT handler
```

---

## Summary of Possible Errors

### 1. **Database & Schema**

| Error | Location | Description |
|-------|----------|-------------|
| **Missing `resume_files` table** | `app/main.py`, `app/routers/resume.py` | If Alembic migrations not run, resume upload returns 503. Lifespan checks table existence and logs warning. |
| **Database URL format** | `app/database.py` | Only replaces `postgresql://` with `postgresql+asyncpg://`. If URL is already `postgresql+asyncpg://`, no change (correct). |
| **pg_dump URL** | `app/tasks/db_backup.py` | Replaces `postgresql+asyncpg://` with `postgresql://` for pg_dump. Fails if URL uses a different scheme. |

### 2. **Async & Fire-and-Forget**

| Error | Location | Description |
|-------|----------|-------------|
| **Unawaited `create_task`** | `app/tasks/db_backup.py:93` | `asyncio.create_task(send_telegram_message(...))` is fire-and-forget. Task may not complete before process exit; exceptions are not propagated. |

### 3. **Exception Handling**

| Error | Location | Description |
|-------|----------|-------------|
| **Broad `except Exception`** | Multiple routers, tasks | Swallows all errors; can hide bugs. Examples: `app/routers/briefing.py` (many), `app/routers/resume.py`, `app/tasks/*.py`. |
| **Bare `raise` after logging** | `app/routers/resume.py:146` | Re-raises after `_dbg`; original traceback preserved. Fine, but generic `Exception` catch may hide root cause. |
| **`list_resumes` re-raises generic Exception** | `app/routers/resume.py:186-188` | On non-ProgrammingError, re-raises without wrapping; client gets 500 with minimal context. |

### 4. **Type & Validation**

| Error | Location | Description |
|-------|----------|-------------|
| **`jd_text` type after URL extract** | `app/routers/jobs.py:379-383` | `extract_jd_from_url` returns `str \| dict`. If dict with `extracted: False`, HTTPException is raised. If dict with `extracted: True` (not returned by jd_extractor), `jd_text` would be a dict and `len(jd_text)` would be wrong. Currently safe because jd_extractor only returns dict on error. |
| **JWT `sub` type** | `app/dependencies.py:48-49` | `user_id = payload.get("sub")` may be str; `User.id` is UUID. SQLAlchemy/PostgreSQL usually handle this, but explicit casting would be safer. |

### 5. **Deprecated APIs**

| Error | Location | Description |
|-------|----------|-------------|
| **`datetime.utcnow()`** | `app/routers/content.py`, `app/routers/briefing.py`, `app/tasks/db_backup.py` | Deprecated in Python 3.12+. Prefer `datetime.now(timezone.utc)`. |

### 6. **Transaction & Commit**

| Error | Location | Description |
|-------|----------|-------------|
| **Double commit** | `app/routers/resume.py:114-121`, `236-245`, `261-268` | `commit` → `log_activity` → `commit` again. `log_activity` adds to same session; second commit is redundant but not incorrect. |
| **Deleted object access** | `app/routers/resume.py:264-267` | After `db.delete(resume)` and `commit`, `resume.version` and `resume.filename` are used. With `expire_on_commit=False`, attributes remain in memory; generally safe. |

### 7. **Configuration & Security**

| Error | Location | Description |
|-------|----------|-------------|
| **Admin API unconfigured** | `app/routers/admin.py:12-13` | If `admin_api_key` is empty, backup endpoint returns 503. |
| **CORS in debug** | `app/main.py:102-110` | In debug mode, allows `frontend_url` and `localhost:3000`. Ensure `frontend_url` is set correctly in production. |

### 8. **AI Service**

| Error | Location | Description |
|-------|----------|-------------|
| **`call_claude` returns `None`** | `app/services/ai_service.py:81` | On non-retryable APIError, returns `None`. Callers must handle None (e.g. jobs, profile, content routers). |
| **`message.content[0].text`** | `app/services/ai_service.py:76` | Assumes `content[0]` exists and has `.text`. Empty or malformed responses can raise `IndexError` or `AttributeError`. |

### 9. **HTTPException Usage**

| Error | Location | Description |
|-------|----------|-------------|
| **Positional args** | `app/routers/content_studio.py` | `HTTPException(404, "Topic not found")` works (status_code, detail) but keyword args are clearer. |

### 10. **Debug / Logging**

| Error | Location | Description |
|-------|----------|-------------|
| **Hardcoded paths** | `app/main.py:51`, `app/exception_handler:162` | `Path(__file__).parent.parent / ".cursor" / "debug.log"` and `debug_resume.log` are hardcoded. May fail if run from different cwd. |
| **Debug middleware writes on every resume request** | `app/main.py:46-56` | Writes to `debug.log` on every `/api/resume` request; can cause I/O overhead. |

### 11. **Scheduler**

| Error | Location | Description |
|-------|----------|-------------|
| **Task failure** | `app/tasks/*.py` | Most tasks catch `Exception`, log, and continue. Failures are not surfaced to users; only logs. |
| **DB session in tasks** | `app/tasks/db.py` | `get_task_session` rolls back on exception. Tasks must use this context; missing usage can leave orphaned sessions. |

### 12. **JD Extractor**

| Error | Location | Description |
|-------|----------|-------------|
| **Return type inconsistency** | `app/services/jd_extractor.py` | Returns `str` on success, `dict` on generic exception. Jobs router checks `isinstance(result, dict)` before using dict. Logic is correct. |

---

## Summary Table

| Category | Count | Severity |
|----------|-------|----------|
| Database/Schema | 3 | Medium |
| Async/Fire-and-forget | 1 | Low |
| Exception handling | 4+ | Low–Medium |
| Type/Validation | 2 | Low |
| Deprecated APIs | 1 | Low |
| Transaction | 2 | Low |
| Config/Security | 2 | Low |
| AI Service | 2 | Medium |
| HTTPException | 1 | Cosmetic |
| Debug/Logging | 2 | Low |
| Scheduler | 2 | Low |
| JD Extractor | 1 | Low |

---

## Quick Reference

- **Main entry**: `app/main.py` → FastAPI app with lifespan
- **Auth**: `get_current_user` (JWT), `get_current_user_or_n8n` (JWT or n8n secret)
- **DB**: `get_db` for request-scoped sessions; `get_task_session` for scheduler tasks
- **AI**: `app/services/ai_service.py` → `call_claude`, `analyze_jd`, `extract_profile`, etc.
- **Resume**: `upload_resume` → `ResumeFile` model, `resume_files` table
- **Scheduler**: `app/scheduler.py` → `start_scheduler` / `stop_scheduler` in lifespan
