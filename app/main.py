import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .services.telegram_service import register_webhook
    from .config import get_settings

    settings = get_settings()
    if settings.telegram_bot_token and settings.app_url:
        webhook_url = f"{settings.app_url}/api/telegram/webhook"
        await register_webhook(webhook_url, settings.telegram_webhook_secret)
        logger.info(f"Telegram webhook registered: {webhook_url}")
    yield


class TrailingSlashMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path != "/" and request.url.path.endswith("/"):
            scope = request.scope
            scope["path"] = scope["path"].rstrip("/")
            if "raw_path" in scope and isinstance(scope["raw_path"], (bytes, bytearray)):
                scope["raw_path"] = scope["raw_path"].rstrip(b"/")
        return await call_next(request)


app = FastAPI(title="JobOS API", version="0.2.0", lifespan=lifespan, redirect_slashes=False)

app.add_middleware(TrailingSlashMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(companies.router, prefix="/api/companies", tags=["companies"])
app.include_router(contacts.router, prefix="/api/contacts", tags=["contacts"])
app.include_router(content.router, prefix="/api/content", tags=["content"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(briefing.router, prefix="/api/briefing", tags=["briefing"])
app.include_router(briefings_user.router, prefix="/api/briefings", tags=["briefings"])
app.include_router(daily_logs.router, prefix="/api/daily-logs", tags=["daily-logs"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["telegram"])
app.include_router(interviews.router, prefix="/api/interviews", tags=["interviews"])


@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "ok"}

