import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .services.telegram_service import register_webhook
    from .config import get_settings

    settings = get_settings()
    if settings.telegram_bot_token and settings.app_url:
        await register_webhook(settings.app_url, settings.telegram_webhook_secret)
        logger.info("Telegram webhook registered")
    yield


app = FastAPI(title="JobOS API", version="0.2.0", lifespan=lifespan, redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .routers import analytics, auth, briefing, companies, contacts, content, jobs, profile, telegram  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(companies.router, prefix="/api/companies", tags=["companies"])
app.include_router(contacts.router, prefix="/api/contacts", tags=["contacts"])
app.include_router(content.router, prefix="/api/content", tags=["content"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(briefing.router, prefix="/api/briefing", tags=["briefing"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["telegram"])


@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "ok"}

