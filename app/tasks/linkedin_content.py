"""LinkedIn content engine — generates post draft at 7:00 PM IST."""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update

from app.config import get_settings
from app.models.content import ContentCalendar
from app.models.profile import ProfileDNA
from app.models.user import User
from app.services.telegram_service import send_telegram_message
from app.services.ai_service import generate_content_draft
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


async def linkedin_content_task() -> None:
    """
    Runs at 7:00 PM IST (1:30 PM UTC) Mon-Sat.
    Pulls tomorrow's topic from content_calendar + profile.
    Calls generate_content_draft() for Claude-generated post.
    Saves draft to DB, sends to Telegram for review.
    """
    settings = get_settings()
    chat_id = settings.owner_telegram_chat_id
    owner_email = settings.owner_email

    if not chat_id or not owner_email:
        logger.warning("LinkedIn content: owner not configured, skipping")
        return

    tomorrow_ist = (datetime.now(IST) + timedelta(days=1)).date()
    logger.info(f"LinkedIn content running for tomorrow: {tomorrow_ist}")

    try:
        async with get_task_session() as db:
            # Find owner user
            result = await db.execute(
                select(User).where(User.email == owner_email)
            )
            user = result.scalar_one_or_none()
            if not user:
                logger.error(f"LinkedIn content: user not found for {owner_email}")
                return

            # Get tomorrow's topic (only if status is Planned)
            result = await db.execute(
                select(ContentCalendar).where(
                    ContentCalendar.user_id == user.id,
                    ContentCalendar.scheduled_date == tomorrow_ist,
                    ContentCalendar.status == 'Planned',
                ).limit(1)
            )
            topic_row = result.scalar_one_or_none()

            if not topic_row:
                logger.info(f"LinkedIn content: no planned topic for {tomorrow_ist}, skipping")
                return

            # Get profile for voice/positioning
            result = await db.execute(
                select(ProfileDNA).where(ProfileDNA.user_id == user.id).limit(1)
            )
            profile = result.scalar_one_or_none()

        # Build profile dict for generate_content_draft(topic, category, profile)
        # The function does json.dumps(profile) into the prompt.
        profile_dict = {}
        if profile:
            profile_dict = {
                "positioning_statement": profile.positioning_statement or "",
                "core_skills": profile.core_skills or [],
                "resume_keywords": profile.resume_keywords or [],
                "target_roles": profile.target_roles or [],
                "full_name": profile.full_name or "",
            }
        else:
            profile_dict = {
                "positioning_statement": "Senior growth leader in B2C consumer tech",
                "core_skills": ["growth marketing", "user acquisition", "GenAI", "performance marketing"],
                "resume_keywords": [],
                "target_roles": ["VP Growth", "Head of Growth", "Director Growth"],
                "full_name": "Abhinav",
            }

        # Call existing AI wrapper
        draft = await generate_content_draft(
            topic=topic_row.topic,
            category=topic_row.category,
            profile=profile_dict,
        )

        if not draft:
            await send_telegram_message(
                chat_id,
                f"✍️ LINKEDIN CONTENT\n\n"
                f"Failed to generate draft for tomorrow.\n"
                f"Topic: {topic_row.topic}\n"
                f"Category: {topic_row.category}\n\n"
                f"Write manually or try /test-content again later."
            )
            return

        # Save draft to content_calendar
        async with get_task_session() as db:
            await db.execute(
                update(ContentCalendar)
                .where(ContentCalendar.id == topic_row.id)
                .values(draft_text=draft, status='Drafted')
            )
            await db.commit()

        # Send to Telegram — NO markdown separators (--- breaks Telegram)
        msg = (
            f"✍️ LINKEDIN DRAFT for {tomorrow_ist.strftime('%A, %b %d')}\n\n"
            f"Topic: {topic_row.topic}\n"
            f"Category: {topic_row.category}\n\n"
            f"= = = = = = = = = =\n\n"
            f"{draft}\n\n"
            f"= = = = = = = = = =\n\n"
            f"Review and edit tonight. Post tomorrow 9 AM."
        )

        await send_telegram_message(chat_id, msg)
        logger.info(f"LinkedIn content draft sent for {tomorrow_ist}")

    except Exception as e:
        logger.error(f"LinkedIn content failed: {e}", exc_info=True)
