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
from app.services.ai_service import generate_company_quick_research

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/company-research", tags=["company-research"])


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
            result = await generate_company_quick_research(
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


@router.post("/generate-deep-prompt")
async def generate_deep_prompt(
    request: ResearchRequest,
    current_user=Depends(get_current_user),
) -> dict:
    """Generate a comprehensive prompt for deep research in Claude.ai"""
    custom_section = ""
    if request.custom_questions:
        questions = request.custom_questions.strip().split("\n")
        custom_section = "\n".join(f"- {q.strip()}" for q in questions if q.strip())

    prompt = f"""# Company Deep Research: {request.company_name}

You are a senior strategy consultant preparing a comprehensive company intelligence briefing for a VP-level Growth candidate interviewing at {request.company_name}.

## Instructions
Use web search to gather CURRENT data (2024-2025). This is interview prep - accuracy and recency matter.

## Required Sections

### 1. Company Overview
- Full timeline: founding → key milestones → current state
- Latest financials: Revenue, GMV, MAU, DAU, Orders (with YoY growth)
- IPO status / DRHP numbers if applicable
- Org structure and leadership team
- Business verticals breakdown

### 2. Business Model Deep-Dive
- Revenue streams with % contribution to P&L
- Unit economics: AOV, CAC, LTV, take rate
- Top categories and growth trajectory
- Monetization methods

### 3. Market & Competitive Landscape
- TAM / SAM / SOM with methodology
- Market share vs 5-6 key competitors
- For each competitor: business model, revenue, strengths, weaknesses, threat level

### 4. User Analysis
- ICP (Ideal Customer Profile) for each segment
- 4+ detailed personas with demographics, goals, pain points
- Acquisition → Onboarding → Engagement → Retention analysis

### 5. Product & App Deep-Dive
- What's working well / what's not
- Customer POV analysis
- Seller POV analysis (if applicable)

### 6. Strategic Analysis
- Current challenges and issues (include seller issues if B2B2C)
- Future opportunities (2-3 year horizon)
- How AI will revolutionize this business

### 7. Culture & Values
- Company mantras/principles with real examples
- What they look for in senior hires

### 8. Interview Prep
- 10 likely questions with suggested answer angles
- Key talking points with supporting data
- Red flags to avoid
- Topics for further research

## Custom Questions
{custom_section if custom_section else "None specified"}

## Output Guidelines
- Include specific numbers with sources
- Mark estimates clearly
- Use tables for comparisons
- Be comprehensive - this is for a VP-level interview"""

    return {
        "company_name": request.company_name,
        "prompt": prompt,
        "instructions": "Copy this prompt to Claude.ai (with web search enabled) for comprehensive research.",
    }


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
