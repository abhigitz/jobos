from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.company import Company
from app.models.content import ContentCalendar
from app.models.contact import Contact
from app.models.daily_log import DailyLog
from app.models.jd_keyword import JDKeyword
from app.models.job import Job
from app.models.profile import ProfileDNA
from app.models.user import User
from app.services.ai_service import (
    analyze_jd_patterns,
    generate_morning_briefing,
    generate_midday_check,
    generate_content_topics,
    generate_interview_prep,
    generate_market_intel,
    generate_weekly_review,
)
from app.services.telegram_service import send_telegram_message


router = APIRouter()
settings = get_settings()


async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != settings.n8n_api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


async def _active_users(db: AsyncSession):
    rows = (
        await db.execute(
            select(User).where(User.is_active.is_(True), User.telegram_chat_id.is_not(None))
        )
    ).scalars().all()
    return rows


@router.post("/morning")
async def morning_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    today = date.today()
    for user in users:
        try:
            jobs = (
                await db.execute(
                    select(Job).where(Job.user_id == user.id, Job.is_deleted.is_(False))
                )
            ).scalars().all()
            logs = (
                await db.execute(
                    select(DailyLog).where(DailyLog.user_id == user.id)
                )
            ).scalars().all()

            contacts_due = (
                await db.execute(
                    select(Contact).where(
                        Contact.user_id == user.id,
                        Contact.is_deleted.is_(False),
                        Contact.follow_up_date.is_not(None),
                        Contact.follow_up_date <= today,
                        Contact.referral_status != 'Outcome',
                    )
                )
            ).scalars().all()

            next_company = (
                await db.execute(
                    select(Company)
                    .where(Company.user_id == user.id)
                    .order_by(Company.last_researched.asc().nulls_first())
                    .limit(1)
                )
            ).scalars().first()

            keyword_gaps = (
                await db.execute(
                    select(JDKeyword)
                    .where(
                        JDKeyword.user_id == user.id,
                        JDKeyword.in_profile_dna.is_(False),
                    )
                    .order_by(JDKeyword.frequency_count.desc())
                    .limit(5)
                )
            ).scalars().all()

            data = {
                "jobs": [j.status for j in jobs],
                "logs": [l.log_date for l in logs],
                "today": today,
                "contacts_due": [
                    {"name": c.name, "company": c.company, "last_response": c.response}
                    for c in contacts_due
                ],
                "next_company": (
                    {
                        "name": next_company.name,
                        "sector": next_company.sector,
                        "lane": next_company.lane,
                    }
                    if next_company
                    else None
                ),
                "keyword_gaps": [
                    {"keyword": k.keyword, "frequency": k.frequency_count}
                    for k in keyword_gaps
                ],
            }

            text = await generate_morning_briefing(data)
            if text:
                await send_telegram_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            # log and continue to next user
            import logging

            logging.getLogger(__name__).error("morning briefing failed for user %s: %s", user.id, e)
    return {"status": "ok"}


@router.post("/midday")
async def midday_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    for user in users:
        try:
            logs = (
                await db.execute(
                    select(DailyLog).where(DailyLog.user_id == user.id)
                )
            ).scalars().all()
            data = {"logs": [l.jobs_applied for l in logs]}
            text = await generate_midday_check(data)
            if text:
                await send_telegram_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).error("midday briefing failed for user %s: %s", user.id, e)
    return {"status": "ok"}


@router.post("/evening-prompt")
async def evening_prompt(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    for user in users:
        try:
            text = (
                "Evening check-in\n\n"
                "1. How many roles did you apply to today?\n"
                "2. How many new connections did you start?\n"
                "3. Any interviews scheduled?\n"
                "4. What's your top priority for tomorrow?"
            )
            await send_telegram_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).error("evening prompt failed for user %s: %s", user.id, e)
    return {"status": "ok"}


@router.post("/content-draft")
async def content_draft_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    from app.services.ai_service import generate_content_draft
    from app.models.profile import ProfileDNA

    users = await _active_users(db)
    tomorrow = date.today() + timedelta(days=1)
    for user in users:
        try:
            # auto-replenish topics if fewer than 3 planned
            remaining = (
                await db.execute(
                    select(func.count()).where(
                        ContentCalendar.user_id == user.id,
                        ContentCalendar.status == "Planned",
                        ContentCalendar.scheduled_date >= date.today(),
                    )
                )
            ).scalar_one()

            prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == user.id))
            profile = prof_res.scalar_one_or_none()
            profile_dict = {}
            if profile is not None:
                profile_dict = {
                    "full_name": profile.full_name,
                    "positioning_statement": profile.positioning_statement,
                    "target_roles": profile.target_roles,
                }

            if remaining < 3:
                topics = await generate_content_topics(profile_dict)
                if topics:
                    last_date_row = (
                        await db.execute(
                            select(func.max(ContentCalendar.scheduled_date)).where(
                                ContentCalendar.user_id == user.id
                            )
                        )
                    ).scalar_one()
                    start_date = last_date_row or date.today()
                    for idx, t in enumerate(topics[:7]):
                        db.add(
                            ContentCalendar(
                                user_id=user.id,
                                scheduled_date=start_date + timedelta(days=idx + 1),
                                topic=t.get("topic"),
                                category=t.get("category"),
                                status="Planned",
                            )
                        )
                    await db.commit()

            item = (
                await db.execute(
                    select(ContentCalendar).where(
                        ContentCalendar.user_id == user.id,
                        ContentCalendar.scheduled_date == tomorrow,
                    )
                )
            ).scalars().first()
            if not item:
                continue

            draft = await generate_content_draft(item.topic or "", item.category or "", profile_dict)
            if draft:
                item.draft_text = draft
                item.status = "Drafted"
                await db.commit()
                await send_telegram_message(user.telegram_chat_id, draft)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).error("content draft briefing failed for user %s: %s", user.id, e)
    return {"status": "ok"}


@router.post("/weekly-review")
async def weekly_review_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    for user in users:
        try:
            logs = (
                await db.execute(
                    select(DailyLog).where(
                        DailyLog.user_id == user.id,
                        DailyLog.log_date >= week_start,
                        DailyLog.log_date <= week_end,
                    )
                )
            ).scalars().all()
            data = {
                "logs": [
                    {
                        "log_date": l.log_date,
                        "jobs_applied": l.jobs_applied,
                        "connections_sent": l.connections_sent,
                    }
                    for l in logs
                ]
            }
            text = await generate_weekly_review(data)
            if text:
                await send_telegram_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).error("weekly review briefing failed for user %s: %s", user.id, e)


@router.post("/company-deep-dive")
async def company_deep_dive_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    from app.services.ai_service import generate_company_deep_dive

    users = await _active_users(db)
    results: list[dict] = []
    for user in users:
        try:
            company = (
                await db.execute(
                    select(Company)
                    .where(Company.user_id == user.id)
                    .order_by(Company.last_researched.asc().nulls_first())
                    .limit(1)
                )
            ).scalars().first()
            if not company:
                continue

            prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == user.id))
            profile = prof_res.scalar_one_or_none()
            profile_dict = {"target_roles": profile.target_roles if profile else []}

            deep_dive = await generate_company_deep_dive(company.name, company.sector, profile_dict)
            if not deep_dive:
                continue

            company.deep_dive_content = deep_dive
            company.deep_dive_done = True
            company.last_researched = datetime.utcnow()
            await db.commit()

            text = (
                f"🏢 Daily Deep-Dive: {company.name}\n\n"
                f"{deep_dive}\n\n"
                f"❓ Practice: \"How would you scale user acquisition for {company.name}?\""
            )
            await send_telegram_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
            results.append({"user_id": str(user.id), "company": company.name})
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).error("company deep dive failed for user %s: %s", user.id, e)
    return {"success": True, "results": results}


@router.post("/jd-patterns")
async def jd_patterns_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    now = datetime.utcnow()
    fourteen_days_ago = now - timedelta(days=14)
    for user in users:
        try:
            base_q = select(Job).where(
                Job.user_id == user.id,
                Job.is_deleted.is_(False),
                Job.created_at >= fourteen_days_ago,
                Job.jd_text.is_not(None),
                Job.jd_text != "",
            )
            good = (
                await db.execute(base_q.where(Job.fit_score.is_not(None), Job.fit_score >= 7))
            ).scalars().all()
            jobs = good
            if len(jobs) < 3:
                jobs = (await db.execute(base_q)).scalars().all()
            if not jobs:
                continue

            prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == user.id))
            profile = prof_res.scalar_one_or_none()
            resume_keywords = profile.resume_keywords if profile and profile.resume_keywords else []

            jd_texts = [j.jd_text for j in jobs if j.jd_text]  # type: ignore[list-item]
            analysis = await analyze_jd_patterns(jd_texts, resume_keywords)
            if not analysis:
                continue

            top_keywords = analysis.get("top_keywords") or []
            for kw in top_keywords:
                keyword = kw.get("keyword")
                freq = kw.get("frequency", 0)
                in_profile = keyword in resume_keywords
                if not keyword:
                    continue
                existing = (
                    await db.execute(
                        select(JDKeyword).where(
                            JDKeyword.user_id == user.id,
                            JDKeyword.keyword == keyword,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.frequency_count = freq
                    existing.in_profile_dna = in_profile
                else:
                    db.add(
                        JDKeyword(
                            user_id=user.id,
                            keyword=keyword,
                            frequency_count=freq,
                            in_profile_dna=in_profile,
                        )
                    )
            await db.commit()

            candidate_covers = analysis.get("candidate_covers") or []
            gaps = analysis.get("gaps") or []
            coverage_score = analysis.get("coverage_score")

            lines = [
                "🔬 Weekly JD Pattern Analysis",
                "",
                f"Analyzed {len(jd_texts)} JDs from last 14 days.",
                "",
                "Top Keywords:",
            ]
            for kw in top_keywords:
                k = kw.get("keyword")
                freq = kw.get("frequency")
                mark = "✅" if k in candidate_covers else "❌ MISSING"
                lines.append(f"• {k} ({freq} JDs) {mark}")

            if coverage_score is not None:
                lines.append("")
                lines.append(f"Coverage: {coverage_score}%")

            gap_recommendations = analysis.get("gap_recommendations") or []
            if gap_recommendations:
                lines.append("")
                lines.append("Gaps to address:")
                for idx, rec in enumerate(gap_recommendations, start=1):
                    lines.append(f"{idx}. {rec}")

            await send_telegram_message(user.telegram_chat_id, "\n".join(lines))  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).error("jd patterns briefing failed for user %s: %s", user.id, e)
    return {"success": True}


@router.post("/interview-prep")
async def interview_prep_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    now = datetime.utcnow()
    window_end = now + timedelta(hours=48)
    any_found = False
    for user in users:
        try:
            jobs = (
                await db.execute(
                    select(Job).where(
                        Job.user_id == user.id,
                        Job.status == "Interview",
                        Job.interview_date.is_not(None),
                        Job.interview_date >= now,
                        Job.interview_date <= window_end,
                        Job.prep_notes.is_(None),
                    )
                )
            ).scalars().all()
            if not jobs:
                continue
            any_found = True

            prof_res = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == user.id))
            profile = prof_res.scalar_one_or_none()
            profile_dict: dict[str, Any] = {}
            if profile is not None:
                profile_dict = {
                    "full_name": profile.full_name,
                    "positioning_statement": profile.positioning_statement,
                    "core_skills": profile.core_skills or [],
                    "achievements": profile.achievements or {},
                }

            for job in jobs:
                comp = (
                    await db.execute(
                        select(Company).where(
                            Company.user_id == user.id,
                            Company.name == job.company_name,
                        )
                    )
                ).scalars().first()
                company_intel = comp.deep_dive_content if comp and comp.deep_dive_content else ""

                prep_doc = await generate_interview_prep(
                    job.company_name,
                    job.role_title,
                    job.jd_text or "",
                    company_intel,
                    profile_dict,
                )
                if not prep_doc:
                    continue
                job.prep_notes = prep_doc
                await db.commit()

                hours = (job.interview_date - now).total_seconds() / 3600  # type: ignore[operator]
                text = (
                    f"🎯 Interview Prep: {job.company_name} — {job.role_title}\n"
                    f"Interview in {hours:.0f} hours\n\n"
                    f"{prep_doc}"
                )
                await send_telegram_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).error("interview prep briefing failed for user %s: %s", user.id, e)
    if not any_found:
        return {"success": True, "message": "No upcoming interviews"}
    return {"success": True}


@router.post("/market-intel")
async def market_intel_briefing(
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    users = await _active_users(db)
    for user in users:
        try:
            lane1 = (
                await db.execute(
                    select(Company)
                    .where(Company.user_id == user.id, Company.lane == 1)
                    .order_by(Company.name)
                )
            ).scalars().all()
            remaining_needed = 15 - len(lane1)
            lane2: list[Company] = []
            if remaining_needed > 0:
                lane2 = (
                    await db.execute(
                        select(Company)
                        .where(Company.user_id == user.id, Company.lane == 2)
                        .order_by(Company.name)
                        .limit(remaining_needed)
                    )
                ).scalars().all()
            selected = (lane1 + lane2)[:15]
            if not selected:
                continue
            names = [c.name for c in selected]
            digest = await generate_market_intel(names)
            if not digest:
                continue
            text = (
                f"{digest}\n\n"
                "⚠️ Based on Claude's training data — verify time-sensitive claims before acting."
            )
            await send_telegram_message(user.telegram_chat_id, text)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).error("market intel briefing failed for user %s: %s", user.id, e)
    return {"success": True}
