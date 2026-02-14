"""Company Deep Research API — AI-generated research for interview preparation."""

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.dependencies import get_current_user
from app.models.company_research import CompanyResearch
from app.schemas.research import ResearchRequest, ResearchResponse
from app.services.ai_service import generate_company_deep_research

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["Research"])


async def _process_research_background(research_id: str, user_id: str) -> None:
    """Background task: call AI, parse response, update DB."""
    async with AsyncSessionLocal() as db:
        research = await db.get(CompanyResearch, UUID(research_id))
        if not research or research.user_id != UUID(user_id):
            logger.warning(f"Research {research_id} not found or user mismatch")
            return

        research.status = "processing"
        await db.commit()

        try:
            result = await generate_company_deep_research(
                research.company_name, research.custom_questions
            )
            if result:
                research.research_data = result
                research.status = "completed"
            else:
                research.status = "failed"
        except Exception as e:
            logger.exception(f"Research failed for {research.company_name}: {e}")
            research.status = "failed"

        await db.commit()
        logger.info(f"Research {research_id} completed with status {research.status}")


@router.post("/generate", response_model=ResearchResponse, status_code=201)
async def start_research(
    payload: ResearchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ResearchResponse:
    """
    Start new company research. Returns immediately; processing runs in background.

    **Request:** ResearchRequest (company_name, custom_questions?)
    **Response:** ResearchResponse with id, status=pending
    **Errors:** 401 (unauthorized)
    """
    research = CompanyResearch(
        user_id=current_user.id,
        company_name=payload.company_name.strip(),
        custom_questions=payload.custom_questions.strip() if payload.custom_questions else None,
        status="pending",
    )
    db.add(research)
    await db.commit()
    await db.refresh(research)

    background_tasks.add_task(
        _process_research_background, str(research.id), str(current_user.id)
    )

    return ResearchResponse(
        id=research.id,
        company_name=research.company_name,
        status=research.status,
        research_data=research.research_data,
        created_at=research.created_at,
    )


@router.get("/{research_id}", response_model=ResearchResponse, status_code=200)
async def get_research(
    research_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> ResearchResponse:
    """
    Get a single research by ID.

    **Response:** ResearchResponse
    **Errors:** 404 (not found), 401 (unauthorized)
    """
    research = await db.get(CompanyResearch, research_id)
    if research is None or research.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Research not found")
    return ResearchResponse(
        id=research.id,
        company_name=research.company_name,
        status=research.status,
        research_data=research.research_data,
        created_at=research.created_at,
    )


@router.get("", response_model=list[ResearchResponse], status_code=200)
async def list_researches(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[ResearchResponse]:
    """
    List all researches for the current user, ordered by created_at desc.

    **Response:** list[ResearchResponse]
    **Errors:** 401 (unauthorized)
    """
    result = await db.execute(
        select(CompanyResearch)
        .where(CompanyResearch.user_id == current_user.id)
        .order_by(CompanyResearch.created_at.desc())
    )
    researches = result.scalars().all()
    return [
        ResearchResponse(
            id=r.id,
            company_name=r.company_name,
            status=r.status,
            research_data=r.research_data,
            created_at=r.created_at,
        )
        for r in researches
    ]


@router.delete("/{research_id}", status_code=200)
async def delete_research(
    research_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict:
    """
    Delete a research.

    **Response:** {status: "deleted"}
    **Errors:** 404 (not found), 401 (unauthorized)
    """
    research = await db.get(CompanyResearch, research_id)
    if research is None or research.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Research not found")
    await db.delete(research)
    await db.commit()
    return {"status": "deleted"}
