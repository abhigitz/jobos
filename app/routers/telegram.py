import logging
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.daily_log import DailyLog
from app.models.job import Job
from app.models.profile import ProfileDNA
from app.models.user import User
from app.routers.jobs import analyze_jd_endpoint, save_from_analysis
from app.routers.profile import extract_profile_from_resume
from app.schemas.jobs import JDAnalyzeRequest, JobCreate, SaveFromAnalysisRequest
from app.schemas.profile import ProfileExtractRequest
from app.services.telegram_service import send_telegram_message

logger = logging.getLogger(__name__)


router = APIRouter()
settings = get_settings()


async def _get_user_by_chat(db: AsyncSession, chat_id: int):
    res = await db.execute(select(User).where(User.telegram_chat_id == chat_id))
    return res.scalar_one_or_none()


@router.post("/webhook")
async def telegram_webhook(
    payload: dict,
    x_telegram_bot_api_secret_token: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return {"ok": True}

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text: str = message.get("text", "")

    if not text.startswith("/"):
        await send_telegram_message(chat_id, "Use /help to see available commands.")
        return {"ok": True}

    parts = text.split(" ", 1)
    command = parts[0]
    arg = parts[1].strip() if len(parts) > 1 else ""

    user = await _get_user_by_chat(db, chat_id)

    if command == "/help":
        await send_telegram_message(
            chat_id,
            "/connect email\n/disconnect\n/jd <job description>\n/apply Company | Role | URL | Source\n/status Company | NewStatus\n/pipeline\n/profile <resume>\n/log 3,4,3,y,1,2,y,Company\n/test-evening - Test evening check-in now\n/test-midday - Test midday check now\n/test-morning - Test morning briefing\n/test-content - Test LinkedIn content draft\n/test-review - Test weekly review",
        )
        return {"ok": True}

    if command == "/connect":
        email = arg.strip()
        if not email:
            await send_telegram_message(chat_id, "Usage: /connect you@example.com")
            return {"ok": True}
        res = await db.execute(select(User).where(User.email == email))
        u = res.scalar_one_or_none()
        if not u:
            await send_telegram_message(chat_id, "Email not found. Please register on the dashboard first.")
            return {"ok": True}
        u.telegram_chat_id = chat_id
        await db.commit()
        await send_telegram_message(chat_id, "Telegram connected to your JobOS account.")
        return {"ok": True}

    if user is None:
        await send_telegram_message(chat_id, "Please connect your account first using /connect email@example.com")
        return {"ok": True}

    if command == "/disconnect":
        user.telegram_chat_id = None
        await db.commit()
        await send_telegram_message(chat_id, "Disconnected Telegram from your account.")
        return {"ok": True}

    if command == "/jd":
        if len(arg) < 50:
            await send_telegram_message(chat_id, "Please send a full JD (at least 50 characters).\n\nUsage: /jd ")
            return {"ok": True}

        req = JDAnalyzeRequest(jd_text=arg, jd_url=None)
        result = await analyze_jd_endpoint(req, db=db, current_user=user)  # type: ignore[arg-type]
        a = result.get("analysis", {})

        # Auto-save to Tracking (Telegram = quick dirty flow)
        try:
            save_req = SaveFromAnalysisRequest(
                company_name=result.get("company_name", "Unknown"),
                role_title=result.get("role_title", "Unknown"),
                jd_text=arg,
                jd_url=None,
                fit_score=a.get("fit_score"),
                ats_score=a.get("ats_score"),
                fit_reasoning=a.get("fit_reasoning"),
                salary_range=a.get("salary_range"),
                keywords_matched=a.get("keywords_matched"),
                keywords_missing=a.get("keywords_missing"),
                ai_analysis=a,
                cover_letter=a.get("cover_letter_draft"),
                status="Tracking",
            )
            await save_from_analysis(save_req, db=db, current_user=user)  # type: ignore[arg-type]
        except Exception as e:
            logger.error(f"Telegram /jd auto-save failed: {e}")

        # Build response message
        lines = [
            f"Company: {result.get('company_name', 'Unknown')}",
            f"Role: {result.get('role_title', 'Unknown')}",
            f"ATS Score: {a.get('ats_score', 'N/A')}",
            f"Fit Score: {a.get('fit_score', 'N/A')}",
            "",
            f"Fit: {a.get('fit_reasoning', 'N/A')}",
            "",
            f"Salary: {a.get('salary_range', 'Not specified')}",
            "",
            f"Recommendation: {a.get('customize_recommendation', 'N/A')}",
            "",
            "Saved to Tracking. View in dashboard.",
        ]
        suggestions = a.get("resume_suggestions", [])
        if suggestions:
            lines.insert(-2, "")
            lines.insert(-2, "Resume suggestions:")
            for s in suggestions[:3]:
                lines.insert(-2, f"  - {s}")
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:4000] + "\n...(truncated)"
        await send_telegram_message(chat_id, msg)
        return {"ok": True}

    if command == "/apply":
        try:
            company, role, url, source = [p.strip() for p in arg.split("|")]
        except ValueError:
            await send_telegram_message(chat_id, "Usage: /apply Company | Role | URL | Source")
            return {"ok": True}
        job = Job(
            user_id=user.id,
            company_name=company,
            role_title=role,
            jd_url=url,
            source_portal=source,
            status="Applied",
        )
        db.add(job)
        await db.commit()
        await send_telegram_message(chat_id, f"Added application: {company} - {role}")
        return {"ok": True}

    if command == "/status":
        try:
            company, new_status = [p.strip() for p in arg.split("|")]
        except ValueError:
            await send_telegram_message(chat_id, "Usage: /status Company | NewStatus")
            return {"ok": True}
        res = await db.execute(
            select(Job)
            .where(Job.user_id == user.id, Job.company_name == company, Job.is_deleted.is_(False))
            .order_by(Job.created_at.desc())
        )
        latest = res.scalars().first()
        if not latest:
            await send_telegram_message(chat_id, "No job found for that company.")
            return {"ok": True}
        latest.status = new_status
        await db.commit()
        await send_telegram_message(chat_id, f"Updated status for {company} to {new_status}")
        return {"ok": True}

    if command == "/pipeline":
        rows = (
            await db.execute(
                select(Job.status, func.count()).where(Job.user_id == user.id, Job.is_deleted.is_(False)).group_by(Job.status)
            )
        ).all()
        lines = [f"{status}: {count}" for status, count in rows]
        await send_telegram_message(chat_id, "Pipeline summary:\n" + "\n".join(lines))
        return {"ok": True}

    if command == "/profile":
        if len(arg) < 500:
            await send_telegram_message(chat_id, "Please paste your full resume (at least 500 characters).")
            return {"ok": True}
        req = ProfileExtractRequest(resume_text=arg)
        await extract_profile_from_resume(req, db=db, current_user=user)  # type: ignore[arg-type]
        await send_telegram_message(chat_id, "Profile updated from resume.")
        return {"ok": True}

    if command == "/log":
        # Expected format: 3,4,3,y,1,2,y,Company
        parts = [p.strip() for p in arg.split(",")]
        if len(parts) < 8:
            await send_telegram_message(chat_id, "Usage: /log jobs,connections,comments,y/n,calls,referrals,y/n,DeepDiveCompany")
            return {"ok": True}
        try:
            jobs_applied = int(parts[0])
            connections_sent = int(parts[1])
            comments_made = int(parts[2])
            post_published = parts[3].lower().startswith("y")
            networking_calls = int(parts[4])
            referrals_asked = int(parts[5])
            naukri_updated = parts[6].lower().startswith("y")
            deep_dive_company = parts[7]
        except ValueError:
            await send_telegram_message(chat_id, "Invalid numbers in log command.")
            return {"ok": True}

        today = date.today()
        res = await db.execute(
            select(DailyLog).where(DailyLog.user_id == user.id, DailyLog.log_date == today)
        )
        log = res.scalar_one_or_none()
        if log is None:
            log = DailyLog(
                user_id=user.id,
                log_date=today,
                jobs_applied=jobs_applied,
                connections_sent=connections_sent,
                comments_made=comments_made,
                post_published=post_published,
                networking_calls=networking_calls,
                referrals_asked=referrals_asked,
                naukri_updated=naukri_updated,
                deep_dive_company=deep_dive_company,
            )
            db.add(log)
        else:
            log.jobs_applied = jobs_applied
            log.connections_sent = connections_sent
            log.comments_made = comments_made
            log.post_published = post_published
            log.networking_calls = networking_calls
            log.referrals_asked = referrals_asked
            log.naukri_updated = naukri_updated
            log.deep_dive_company = deep_dive_company
        await db.commit()
        await send_telegram_message(chat_id, "Daily log saved.")
        return {"ok": True}

    if command == "/test-evening":
        from app.tasks.evening_checkin import evening_checkin_task
        await evening_checkin_task()
        return {"ok": True}

    if command == "/test-midday":
        from app.tasks.midday_check import midday_check_task
        await midday_check_task()
        return {"ok": True}

    if command == "/test-morning":
        from app.tasks.morning_briefing import morning_briefing_task
        await morning_briefing_task()
        return {"ok": True}

    if command == "/test-content":
        from app.tasks.linkedin_content import linkedin_content_task
        await linkedin_content_task()
        return {"ok": True}

    if command == "/test-review":
        from app.tasks.weekly_review import weekly_review_task
        await weekly_review_task()
        return {"ok": True}

    if command == "/test-ghost":
        from app.tasks.auto_ghost import auto_ghost_task
        await auto_ghost_task()
        return {"ok": True}

    await send_telegram_message(chat_id, "Unknown command. Use /help.")
    return {"ok": True}


@router.post("/register-webhook")
async def manual_register_webhook():
    """Manually trigger webhook registration with Telegram API."""
    from app.services.telegram_service import register_webhook
    
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not configured")
    
    if not settings.app_url:
        raise HTTPException(status_code=400, detail="APP_URL not configured")
    
    webhook_url = f"{settings.app_url}/api/telegram/webhook"
    success = await register_webhook(webhook_url, settings.telegram_webhook_secret)
    
    if success:
        return {"status": "success", "webhook_url": webhook_url}
    else:
        raise HTTPException(status_code=500, detail="Failed to register webhook with Telegram")
