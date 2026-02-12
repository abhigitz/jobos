"""Background company research triggered on company creation."""
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.company import Company
from app.models.profile import ProfileDNA
from app.services.ai_service import research_company_structured

logger = logging.getLogger(__name__)


async def research_company_background(company_id: str, user_id: str) -> None:
    """Fetch company, run AI research, update DB. Called after response is sent."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.warning("Skipping company research: anthropic_api_key not configured")
        return

    async with AsyncSessionLocal() as db:
        company = await db.get(Company, UUID(company_id))
        if not company:
            logger.warning(f"Company {company_id} not found for research")
            return
        if company.user_id != UUID(user_id):
            logger.warning(f"Company {company_id} user mismatch")
            return
        if company.deep_dive_done:
            return

        prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == company.user_id))
        profile = prof_res.scalar_one_or_none()
        profile_dict = {"target_roles": profile.target_roles if profile else []}

        try:
            result = await research_company_structured(
                company.name, company.sector, profile_dict
            )
        except Exception as e:
            logger.error(f"Company research failed for {company.name}: {e}")
            return

        if not result:
            logger.warning(f"Company research returned no data for {company.name}")
            return

        # Only update empty fields
        if not company.sector and result.get("sector"):
            company.sector = result["sector"]
        if not company.website and result.get("website"):
            company.website = result["website"]
        if not company.hq_city and result.get("hq_city"):
            company.hq_city = result["hq_city"]
        if not company.funding and result.get("funding"):
            company.funding = result["funding"]
        if not company.investors and result.get("investors"):
            company.investors = result["investors"]
        if not company.stage and result.get("stage"):
            company.stage = result["stage"]
        if result.get("deep_dive_content"):
            company.deep_dive_content = result["deep_dive_content"]

        company.deep_dive_done = True
        company.last_researched = datetime.now(timezone.utc)
        await db.commit()
        logger.info(f"Company research complete for {company.name}")
