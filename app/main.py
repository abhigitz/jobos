import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .services.telegram_service import register_webhook
    from .config import get_settings
    from .scheduler import start_scheduler, stop_scheduler
    from sqlalchemy import text
    from .database import engine

    settings = get_settings()
    # Check resume_files table exists (helps debug 500 on upload)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM resume_files LIMIT 1"))
    except Exception as e:
        if "does not exist" in str(e) or "resume_files" in str(e):
            logger.warning("resume_files table not found. Run: alembic upgrade head")
    if settings.telegram_bot_token and settings.app_url:
        webhook_url = f"{settings.app_url}/api/telegram/webhook"
        await register_webhook(webhook_url, settings.telegram_webhook_secret)
        logger.info(f"Telegram webhook registered: {webhook_url}")

    start_scheduler()

    yield

    stop_scheduler()


class DebugResumeMiddleware(BaseHTTPMiddleware):
    """Log resume-related requests for debugging."""
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if "/api/resume" in path:
            logger.info("[DEBUG] resume request method=%s path=%s", request.method, path)
            try:
                from pathlib import Path
                import json, time
                _p = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"
                with open(_p, "a") as f:
                    f.write(json.dumps({"id":"resume_req","timestamp":time.time()*1000,"method":request.method,"path":path}) + "\n")
            except Exception as e:
                logger.warning(f"Debug middleware failed to write log: {e}")
        return await call_next(request)


class TrailingSlashMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path != "/" and request.url.path.endswith("/"):
            scope = request.scope
            scope["path"] = scope["path"].rstrip("/")
            if "raw_path" in scope and isinstance(scope["raw_path"], (bytes, bytearray)):
                scope["raw_path"] = scope["raw_path"].rstrip(b"/")
        return await call_next(request)


from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.dependencies import limiter
from app.config import get_settings
from app.database import get_db

app = FastAPI(title="JobOS API", version="0.2.0", lifespan=lifespan, redirect_slashes=False)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(TrailingSlashMiddleware)
app.add_middleware(DebugResumeMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    logger.info("[%s] %s %s", request_id, request.method, request.url.path)

    response = await call_next(request)

    duration = time.time() - start_time
    logger.info("[%s] %d (%.2fs)", request_id, response.status_code, duration)

    response.headers["X-Request-ID"] = request_id
    return response

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [_settings.frontend_url, "http://localhost:3000"]
        if _settings.debug
        else [_settings.frontend_url]
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .routers import (  # noqa: E402
    activity,
    analytics,
    auth,
    briefing,
    briefings_user,
    companies,
    contacts,
    content,
    content_studio,
    daily_logs,
    interviews,
    jobs,
    profile,
    resume,
    scout,
    search,
    telegram,
)

app.include_router(activity.router, prefix="/api/activity", tags=["activity"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(resume.router, prefix="/api/resume", tags=["resume"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(companies.router, prefix="/api/companies", tags=["companies"])
app.include_router(contacts.router, prefix="/api/contacts", tags=["contacts"])
app.include_router(content.router, prefix="/api/content", tags=["content"])
app.include_router(content_studio.router)
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(briefing.router, prefix="/api/briefing", tags=["briefing"])
app.include_router(briefings_user.router, prefix="/api/briefings", tags=["briefings"])
app.include_router(daily_logs.router, prefix="/api/daily-logs", tags=["daily-logs"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["telegram"])
app.include_router(interviews.router, prefix="/api/interviews", tags=["interviews"])
app.include_router(scout.router, prefix="/api/scout", tags=["scout"])
app.include_router(search.router)


@app.exception_handler(Exception)
async def debug_unhandled_exception(request, exc):
    """Log unhandled exceptions for debug session."""
    if isinstance(exc, HTTPException):
        raise exc
    import traceback
    tb = traceback.format_exc()
    logger.exception("Unhandled exception: %s (path=%s)", exc, request.url.path)
    try:
        from pathlib import Path
        _log_path = Path(__file__).resolve().parent.parent / "debug_resume.log"
        with open(_log_path, "a") as _log:
            import json
            _log.write(json.dumps({"id":"log_unhandled","timestamp":__import__("time").time()*1000,"location":"main.py:exception_handler","message":"Unhandled exception","data":{"path":request.url.path,"error":str(exc),"tb":tb},"hypothesisId":"H1,H2,H3,H4,H5"})+"\n")
    except Exception:
        pass
    from starlette.responses import JSONResponse
    settings = get_settings()
    if settings.debug:
        return JSONResponse(status_code=500, content={"detail": str(exc), "traceback": tb})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health")
async def health_check(db=Depends(get_db)):
    """Deep health check with database connectivity."""
    from sqlalchemy import text

    health: dict = {"status": "ok", "checks": {}}

    try:
        await db.execute(text("SELECT 1"))
        health["checks"]["database"] = "ok"
    except Exception as e:
        health["checks"]["database"] = f"error: {e}"
        health["status"] = "degraded"

    return health

