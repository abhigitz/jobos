import logging
import time
import uuid
from contextlib import asynccontextmanager

import sentry_sdk
from app.config import get_settings
from fastapi import Depends, FastAPI, HTTPException

settings = get_settings()
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        environment=settings.environment or "production",
    )

from fastapi import APIRouter
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

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
        webhook_url = f"{settings.app_url}/api/v1/telegram/webhook"
        await register_webhook(webhook_url, settings.telegram_webhook_secret)
        logger.info(f"Telegram webhook registered: {webhook_url}")

    start_scheduler()

    yield

    stop_scheduler()


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
from app.database import get_db

app = FastAPI(title="JobOS API", version="0.2.0", lifespan=lifespan, redirect_slashes=False)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS must be first in execution order (add last - Starlette runs last-added first)
# so CORS headers are added even on redirect responses (e.g. 307)
# Build allow_origins: FRONTEND_URL from env, plus localhost, plus Lovable deployment
_cors_origins = [
    o for o in [
        settings.frontend_url,
        "http://localhost:3000",
        "http://localhost:5173",
        "https://jobos-1.lovable.app",
    ]
    if o
]
_cors_origins = list(dict.fromkeys(_cors_origins))  # dedupe preserving order
app.add_middleware(TrailingSlashMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.lovable\.app",  # Lovable preview deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


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


@app.middleware("http")
async def redirect_old_api_paths(request: Request, call_next):
    path = request.url.path
    # Redirect /api/health to /health (health is at root level)
    if path == "/api/health":
        if request.method == "GET":
            return RedirectResponse(url="/health", status_code=307)
        request.scope["path"] = "/health"
        return await call_next(request)
    # Rewrite /api/xxx to /api/v1/xxx (except /api/v1 paths)
    # Use path rewrite for ALL methods - 307 redirects break CORS for cross-origin fetch
    if path.startswith("/api/") and not path.startswith("/api/v1/"):
        new_path = path.replace("/api/", "/api/v1/", 1)
        request.scope["path"] = new_path
    return await call_next(request)


from .routers import (  # noqa: E402
    activity,
    admin,
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

# Create v1 API router
api_v1 = APIRouter(prefix="/api/v1")

# Add all routers to v1
api_v1.include_router(activity.router, prefix="/activity", tags=["activity"])
api_v1.include_router(admin.router, prefix="/admin", tags=["admin"])
api_v1.include_router(auth.router, prefix="/auth", tags=["auth"])
api_v1.include_router(profile.router, prefix="/profile", tags=["profile"])
api_v1.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_v1.include_router(companies.router, prefix="/companies", tags=["companies"])
api_v1.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
api_v1.include_router(content.router, prefix="/content", tags=["content"])
api_v1.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_v1.include_router(telegram.router, prefix="/telegram", tags=["telegram"])
api_v1.include_router(briefing.router, prefix="/briefing", tags=["briefing"])
api_v1.include_router(resume.router, prefix="/resume", tags=["resume"])
api_v1.include_router(briefings_user.router, prefix="/briefings", tags=["briefings"])
api_v1.include_router(content_studio.router)
api_v1.include_router(daily_logs.router, prefix="/daily-logs", tags=["daily-logs"])
api_v1.include_router(interviews.router, prefix="/interviews", tags=["interviews"])
api_v1.include_router(scout.router, prefix="/scout", tags=["scout"])
api_v1.include_router(search.router)

# Mount v1 router
app.include_router(api_v1)


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
        _log_path = Path(__file__).resolve().parent / "debug_resume.log"
        with open(_log_path, "a") as _log:
            import json
            _log.write(json.dumps({"id":"log_unhandled","timestamp":__import__("time").time()*1000,"location":"main.py:exception_handler","message":"Unhandled exception","data":{"path":request.url.path,"error":str(exc),"tb":tb},"hypothesisId":"H1,H2,H3,H4,H5"})+"\n")
    except Exception:
        pass
    from starlette.responses import JSONResponse
    if settings.debug:
        return JSONResponse(status_code=500, content={"detail": str(exc), "traceback": tb})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
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

