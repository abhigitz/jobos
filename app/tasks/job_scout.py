"""Scheduled task for Job Scout — fetches jobs from SerpAPI, upserts to scouted_jobs, matches to users."""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.company import Company
from app.models.scout import ScoutedJob, UserScoutedJob, UserScoutPreferences
from app.services.ats_scrapers import fetch_target_company_jobs
from app.services.scout_preferences import get_or_create_preferences
from app.services.scout_scoring import score_job
from app.services.serpapi_service import fetch_jobs_from_serpapi, normalize_company
from app.tasks.db import get_task_session

logger = logging.getLogger(__name__)


async def upsert_scouted_job(db: AsyncSession, job_dict: dict) -> tuple[ScoutedJob, bool]:
    """
    Upsert a scouted job by dedup_hash.
    If exists: update last_seen_at, is_active=True, inactive_reason=None.
    If new: insert full record.

    Returns:
        (ScoutedJob, is_new) — the job instance and whether it was newly inserted.
    """
    dedup_hash = job_dict.get("dedup_hash")
    if not dedup_hash:
        # No dedup_hash — insert as new (shouldn't happen with SerpAPI)
        job = ScoutedJob(
            external_id=job_dict.get("external_id"),
            dedup_hash=dedup_hash,
            title=job_dict["title"],
            company_name=job_dict["company_name"],
            company_name_normalized=job_dict.get("company_name_normalized"),
            location=job_dict.get("location"),
            city=job_dict.get("city"),
            description=job_dict.get("description"),
            salary_min=job_dict.get("salary_min"),
            salary_max=job_dict.get("salary_max"),
            salary_is_estimated=job_dict.get("salary_is_estimated", False),
            source=job_dict.get("source", "serpapi"),
            source_url=job_dict.get("source_url"),
            apply_url=job_dict.get("apply_url"),
            posted_date=job_dict.get("posted_date"),
            scouted_at=job_dict.get("scouted_at") or datetime.now(timezone.utc),
            last_seen_at=job_dict.get("last_seen_at") or datetime.now(timezone.utc),
            is_active=True,
            inactive_reason=None,
            matched_company_id=job_dict.get("matched_company_id"),
            raw_json=job_dict.get("raw_json"),
            search_query=job_dict.get("search_query"),
        )
        db.add(job)
        return job, True

    result = await db.execute(
        select(ScoutedJob).where(ScoutedJob.dedup_hash == dedup_hash)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.last_seen_at = job_dict.get("last_seen_at") or datetime.now(timezone.utc)
        existing.is_active = True
        existing.inactive_reason = None
        if job_dict.get("matched_company_id") is not None:
            existing.matched_company_id = job_dict["matched_company_id"]
        await db.flush()
        return existing, False

    job = ScoutedJob(
        external_id=job_dict.get("external_id"),
        dedup_hash=dedup_hash,
        title=job_dict["title"],
        company_name=job_dict["company_name"],
        company_name_normalized=job_dict.get("company_name_normalized"),
        location=job_dict.get("location"),
        city=job_dict.get("city"),
        description=job_dict.get("description"),
        salary_min=job_dict.get("salary_min"),
        salary_max=job_dict.get("salary_max"),
        salary_is_estimated=job_dict.get("salary_is_estimated", False),
        source=job_dict.get("source", "serpapi"),
        source_url=job_dict.get("source_url"),
        apply_url=job_dict.get("apply_url"),
        posted_date=job_dict.get("posted_date"),
        scouted_at=job_dict.get("scouted_at") or datetime.now(timezone.utc),
        last_seen_at=job_dict.get("last_seen_at") or datetime.now(timezone.utc),
        is_active=True,
        inactive_reason=None,
        matched_company_id=job_dict.get("matched_company_id"),
        raw_json=job_dict.get("raw_json"),
        search_query=job_dict.get("search_query"),
    )
    db.add(job)
    return job, True


async def run_job_scout() -> dict:
    """
    Main job scout task: fetch jobs from SerpAPI, upsert to scouted_jobs,
    mark stale jobs, match to users, optionally send Telegram summary.
    """
    settings = get_settings()
    start = datetime.now(timezone.utc)
    logger.info(f"Job Scout starting at {start.isoformat()}")

    # SerpAPI is optional; we also fetch from ATS (Greenhouse/Lever)

    stats = {"fetched": 0, "new": 0, "updated": 0, "stale_marked": 0, "matches": {}}

    async with get_task_session() as db:
        # 1. Fetch jobs from SerpAPI (if configured)
        serp_jobs: list[dict] = []
        if settings.serpapi_key:
            serp_jobs = await fetch_jobs_from_serpapi()
        else:
            logger.warning("Job Scout: serpapi_key not configured, skipping SerpAPI fetch")
        logger.info(f"Job Scout: fetched {len(serp_jobs)} jobs from SerpAPI")

        # 2. Fetch jobs from target companies (Greenhouse, Lever)
        ats_jobs = await fetch_target_company_jobs()
        logger.info(f"Job Scout: fetched {len(ats_jobs)} jobs from ATS (Greenhouse/Lever)")

        # 3. Merge and deduplicate by dedup_hash
        seen_hashes: set[str] = set()
        jobs: list[dict] = []
        for job in serp_jobs + ats_jobs:
            h = job.get("dedup_hash")
            if h and h not in seen_hashes:
                seen_hashes.add(h)
                jobs.append(job)

        stats["fetched"] = len(jobs)
        if not jobs:
            logger.info("Job Scout: no jobs returned, skipping upsert and matching")
            return stats

        # Build company lookup: normalized_name -> company_id
        companies_result = await db.execute(select(Company.id, Company.name))
        company_norm_to_id: dict[str, uuid.UUID] = {}
        for row in companies_result.all():
            norm = normalize_company(row.name)
            if norm and norm not in company_norm_to_id:
                company_norm_to_id[norm] = row.id

        # 4. Upsert jobs to scouted_jobs
        now = datetime.now(timezone.utc)
        for job_dict in jobs:
            job_dict["last_seen_at"] = now
            # Match company
            cn = job_dict.get("company_name_normalized")
            if cn and cn in company_norm_to_id:
                job_dict["matched_company_id"] = company_norm_to_id[cn]

            _, is_new = await upsert_scouted_job(db, job_dict)
            if is_new:
                stats["new"] += 1
            else:
                stats["updated"] += 1

        await db.commit()

        # 5. Mark stale jobs (not seen in 7+ days)
        stale_cutoff = now - timedelta(days=7)
        stale_result = await db.execute(
            select(ScoutedJob).where(
                ScoutedJob.last_seen_at < stale_cutoff,
                ScoutedJob.is_active.is_(True),
            )
        )
        stale_jobs = stale_result.scalars().all()
        for job in stale_jobs:
            job.is_active = False
            job.inactive_reason = "not_seen_7d"
        stats["stale_marked"] = len(stale_jobs)
        await db.commit()
        if stale_jobs:
            logger.info(f"Job Scout: marked {len(stale_jobs)} jobs as stale (not_seen_7d)")

        # 6. Match jobs to users
        # Get users with scout preferences
        prefs_result = await db.execute(select(UserScoutPreferences.user_id).distinct())
        user_ids = [r[0] for r in prefs_result.all()]

        # Get active scouted jobs
        active_jobs_result = await db.execute(
            select(ScoutedJob).where(ScoutedJob.is_active.is_(True))
        )
        active_jobs = active_jobs_result.scalars().all()

        # Get existing user_scouted_jobs (user_id, scouted_job_id) pairs
        existing_result = await db.execute(
            select(UserScoutedJob.user_id, UserScoutedJob.scouted_job_id)
        )
        existing_pairs = {(r.user_id, r.scouted_job_id) for r in existing_result.all()}

        # Load companies for scoring (job.matched_company_id -> Company)
        company_ids = {j.matched_company_id for j in active_jobs if j.matched_company_id}
        companies_by_id: dict = {}
        if company_ids:
            comp_result = await db.execute(
                select(Company).where(Company.id.in_(company_ids))
            )
            companies_by_id = {c.id: c for c in comp_result.scalars().all()}

        for user_id in user_ids:
            prefs = await get_or_create_preferences(db, user_id)
            min_score = prefs.min_score if prefs.min_score is not None else 30
            matches_this_user = 0

            for job in active_jobs:
                if (user_id, job.id) in existing_pairs:
                    continue

                company = companies_by_id.get(job.matched_company_id) if job.matched_company_id else None
                result = score_job(job, prefs, company)

                if result.total >= min_score:
                    usj = UserScoutedJob(
                        user_id=user_id,
                        scouted_job_id=job.id,
                        relevance_score=result.total,
                        score_breakdown=result.breakdown,
                        match_reasons=result.reasons,
                        status="new",
                    )
                    db.add(usj)
                    existing_pairs.add((user_id, job.id))
                    matches_this_user += 1

            stats["matches"][str(user_id)] = matches_this_user
            if matches_this_user:
                logger.info(f"Job Scout: user {user_id} — {matches_this_user} new matches")

        await db.commit()

    # 7. Send summary to Telegram (optional)
    chat_id = settings.owner_telegram_chat_id
    total_matches = sum(stats["matches"].values())
    if chat_id and settings.telegram_bot_token:
        try:
            from app.services.telegram_service import send_telegram_message

            msg = (
                f"🔍 Job Scout: Found {stats['fetched']} new jobs, "
                f"{total_matches} matches for you."
            )
            await send_telegram_message(chat_id, msg)
        except Exception as e:
            logger.warning(f"Job Scout: failed to send Telegram summary: {e}")

    end = datetime.now(timezone.utc)
    logger.info(
        f"Job Scout complete at {end.isoformat()}: "
        f"fetched={stats['fetched']}, new={stats['new']}, updated={stats['updated']}, "
        f"stale_marked={stats['stale_marked']}, total_matches={total_matches}"
    )
    return stats


async def job_scout_task() -> None:
    """Runs daily at 8:00 AM IST. Discovers jobs from SerpAPI and ATS (Greenhouse/Lever), matches to users."""
    settings = get_settings()
    try:
        stats = await run_job_scout()
        logger.info(
            f"Job Scout task complete: fetched={stats.get('fetched', 0)}, "
            f"new={stats.get('new', 0)}, updated={stats.get('updated', 0)}, "
            f"stale_marked={stats.get('stale_marked', 0)}, "
            f"matches={sum(stats.get('matches', {}).values())}"
        )
    except Exception as e:
        logger.error(f"Job Scout task failed: {e}", exc_info=True)
        try:
            from app.services.telegram_service import send_telegram_message

            chat_id = settings.owner_telegram_chat_id
            if chat_id and settings.telegram_bot_token:
                await send_telegram_message(
                    chat_id,
                    f"Job Scout error: {str(e)[:200]}",
                )
        except Exception:
            pass
