import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.content_post import ContentPost
from app.models.content_topic import ContentTopic
from app.models.profile import ProfileDNA
from app.models.story_prompt_shown import StoryPromptShown
from app.models.user import User
from app.models.user_content_settings import UserContentSettings
from app.models.user_story import UserStory
from app.schemas.content_studio import (
    AddCustomTopicRequest,
    ContentStudioHome,
    GeneratePostRequest,
    GeneratePostResponse,
    MarkPostedRequest,
    RecordEngagementRequest,
    RegenerateRequest,
    SaveStoryRequest,
    StoryPromptOut,
    TopicOut,
)
from app.services.ai_service import generate_content_studio_topics, generate_linkedin_post

router = APIRouter(prefix="/api/content-studio", tags=["content-studio"])
logger = logging.getLogger(__name__)

STORY_PROMPTS = [
    "Describe a moment when a project you believed in failed. What did you learn?",
    "Tell me about a time you had to make a decision with incomplete data.",
    "What's a piece of advice you ignored that turned out to be right?",
    "Describe your worst day at work in the last 5 years. What happened?",
    "Tell me about someone junior who taught you something important.",
    "When did you have to fire someone or let them go? What did you learn?",
    "Describe a time you disagreed with your manager. How did it resolve?",
    "What's the biggest risk you've taken in your career?",
    "Tell me about a product launch that flopped.",
    "When did you have to pivot a strategy mid-flight?",
    "Describe a time you had to deliver bad news to stakeholders.",
    "What's a skill you learned the hard way?",
    "Tell me about a mentor who changed your trajectory.",
    "When did you feel like an impostor? How did you get through it?",
    "Describe a time you had to build trust with a skeptical team.",
    "What's a metric you obsessed over that turned out to be wrong?",
    "Tell me about a time you had to say no to a senior leader.",
    "When did you have to learn something completely new under pressure?",
    "Describe a hiring mistake you made.",
    "What's a piece of feedback that stung but was right?",
    "Tell me about a time you had to cut scope to ship.",
    "When did you have to advocate for someone else's idea?",
    "Describe a time you failed to meet a deadline.",
    "What's a habit you had to unlearn?",
    "Tell me about a time you had to work with someone you didn't like.",
    "When did you have to defend an unpopular decision?",
    "Describe a time you over-engineered a solution.",
    "What's a lesson from a previous job that you applied elsewhere?",
    "Tell me about a time you had to rebuild a broken process.",
    "When did you have to admit you didn't know something?",
    "Describe a time you had to negotiate with a difficult counterpart.",
    "What's a goal you set and missed? What did you learn?",
    "Tell me about a time you had to onboard during chaos.",
    "When did you have to choose between speed and quality?",
    "Describe a time you had to give critical feedback to a peer.",
    "What's a trend you bet on that didn't pan out?",
    "Tell me about a time you had to scale a team quickly.",
    "When did you have to deprioritize something you cared about?",
    "Describe a time you had to fix a mess you didn't create.",
    "What's a conversation you wish you'd had earlier?",
    "Tell me about a time you had to work across time zones.",
    "When did you have to simplify something complex for others?",
    "Describe a time you had to recover from a public mistake.",
    "What's a tool or framework you adopted that changed how you work?",
    "Tell me about a time you had to balance multiple stakeholders.",
    "When did you have to make a call without your manager's input?",
    "Describe a time you had to let go of a project you loved.",
    "What's a blind spot someone pointed out to you?",
    "Tell me about a time you had to rebuild trust after a failure.",
    "When did you have to advocate for yourself in a difficult situation?",
    "Describe a time you had to learn from a competitor.",
    "What's a meeting you wish you'd run differently?",
    "Tell me about a time you had to bridge a gap between teams.",
    "When did you have to make peace with good enough?",
]


async def get_or_create_settings(db: AsyncSession, user_id: UUID) -> UserContentSettings:
    result = await db.execute(
        select(UserContentSettings).where(UserContentSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = UserContentSettings(user_id=user_id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def get_user_profile(db: AsyncSession, user_id: UUID) -> dict:
    result = await db.execute(select(ProfileDNA).where(ProfileDNA.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile is None:
        return {}
    return {
        "full_name": profile.full_name,
        "positioning_statement": profile.positioning_statement,
        "target_roles": profile.target_roles,
        "core_skills": profile.core_skills,
        "achievements": profile.achievements,
        "career_narrative": profile.career_narrative,
        "experience_level": profile.experience_level,
        "years_of_experience": profile.years_of_experience,
    }


async def get_available_topics(
    db: AsyncSession, user_id: UUID, categories: list
) -> list[ContentTopic]:
    result = await db.execute(
        select(ContentTopic)
        .where(ContentTopic.user_id == user_id)
        .where(ContentTopic.status == "available")
        .order_by(ContentTopic.created_at.desc())
        .limit(10)
    )
    return list(result.scalars().all())


async def generate_topics(
    db: AsyncSession,
    user: User,
    categories: list,
    force_new: bool = False,
) -> list[ContentTopic]:
    if force_new:
        await db.execute(
            update(ContentTopic)
            .where(ContentTopic.user_id == user.id)
            .where(ContentTopic.status == "available")
            .values(status="dismissed")
        )
        await db.commit()

    profile = await get_user_profile(db, user.id)
    topics_data = await generate_content_studio_topics(profile, categories)
    if not topics_data:
        return []

    created = []
    for t in topics_data:
        topic = ContentTopic(
            user_id=user.id,
            topic_title=t.get("topic_title", t.get("topic", "")),
            category=t.get("category", "Growth"),
            angle=t.get("angle"),
            suggested_creative=t.get("suggested_creative", "text"),
            status="available",
        )
        db.add(topic)
        created.append(topic)
    await db.commit()
    for t in created:
        await db.refresh(t)
    return created


async def get_todays_prompt(db: AsyncSession, user_id: UUID) -> Optional[StoryPromptOut]:
    today = datetime.now(timezone.utc).date()

    existing = await db.execute(
        select(StoryPromptShown)
        .where(StoryPromptShown.user_id == user_id)
        .where(func.date(StoryPromptShown.shown_at) == today)
        .order_by(StoryPromptShown.shown_at.desc())
        .limit(1)
    )
    shown = existing.scalar_one_or_none()

    if shown:
        if shown.dismissed or shown.answered:
            return None
        return StoryPromptOut(prompt_text=shown.prompt_text)

    recent = await db.execute(
        select(StoryPromptShown.prompt_text)
        .where(StoryPromptShown.user_id == user_id)
        .where(StoryPromptShown.shown_at >= datetime.now(timezone.utc) - timedelta(days=30))
    )
    recent_prompts = {r[0] for r in recent.all()}

    available = [p for p in STORY_PROMPTS if p not in recent_prompts]
    if not available:
        available = STORY_PROMPTS

    prompt_text = random.choice(available)

    new_shown = StoryPromptShown(user_id=user_id, prompt_text=prompt_text)
    db.add(new_shown)
    await db.commit()

    return StoryPromptOut(prompt_text=prompt_text)


def get_time_of_day(dt: datetime) -> str:
    hour = dt.hour
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    else:
        return "evening"


async def get_best_posting_time(db: AsyncSession, user_id: UUID) -> Optional[str]:
    result = await db.execute(
        select(ContentPost.time_of_day, func.count(ContentPost.id))
        .where(ContentPost.user_id == user_id)
        .where(ContentPost.posted_at.isnot(None))
        .where(ContentPost.engagement_recorded_at.isnot(None))
        .group_by(ContentPost.time_of_day)
    )
    rows = result.all()
    if not rows:
        return "morning"
    best = max(rows, key=lambda r: r[1])
    return best[0]


async def calculate_insights(db: AsyncSession, user_id: UUID) -> dict:
    result = await db.execute(
        select(ContentPost)
        .where(ContentPost.user_id == user_id)
        .where(ContentPost.engagement_recorded_at.isnot(None))
    )
    posts = result.scalars().all()
    if len(posts) < 3:
        return {"message": "Post more and record engagement to see insights"}

    total_impressions = sum(p.impressions or 0 for p in posts)
    total_reactions = sum(p.reactions or 0 for p in posts)
    total_comments = sum(p.comments or 0 for p in posts)
    with_image = sum(1 for p in posts if p.had_image)
    with_carousel = sum(1 for p in posts if p.had_carousel)

    return {
        "total_posts_with_engagement": len(posts),
        "avg_impressions": round(total_impressions / len(posts)) if posts else 0,
        "avg_reactions": round(total_reactions / len(posts)) if posts else 0,
        "avg_comments": round(total_comments / len(posts)) if posts else 0,
        "posts_with_image": with_image,
        "posts_with_carousel": with_carousel,
    }


async def get_stories_count(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(
        select(func.count(UserStory.id)).where(UserStory.user_id == user_id)
    )
    return result.scalar() or 0


@router.get("/", response_model=ContentStudioHome)
async def get_content_studio_home(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = await get_or_create_settings(db, current_user.id)

    topics = await get_available_topics(db, current_user.id, settings.categories)
    if len(topics) < 4:
        topics = await generate_topics(db, current_user, settings.categories)

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=now.weekday())
    week_posts = await db.execute(
        select(func.count(ContentPost.id))
        .where(ContentPost.user_id == current_user.id)
        .where(ContentPost.posted_at >= week_start)
    )
    weekly_streak = week_posts.scalar() or 0

    stories_count = await get_stories_count(db, current_user.id)

    story_prompt = await get_todays_prompt(db, current_user.id)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    pending = await db.execute(
        select(ContentPost)
        .where(ContentPost.user_id == current_user.id)
        .where(ContentPost.posted_at <= cutoff)
        .where(ContentPost.engagement_recorded_at.is_(None))
        .order_by(ContentPost.posted_at.desc())
        .limit(3)
    )
    pending_posts = [
        {
            "id": str(p.id),
            "post_text": (p.post_text[:100] + "...") if len(p.post_text) > 100 else p.post_text,
            "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        }
        for p in pending.scalars().all()
    ]

    best_time = await get_best_posting_time(db, current_user.id)

    return ContentStudioHome(
        topics=[TopicOut.model_validate(t) for t in topics[:5]],
        weekly_streak=weekly_streak,
        weekly_goal=settings.weekly_post_goal,
        best_posting_time=best_time,
        story_prompt=story_prompt,
        stories_count=stories_count,
        pending_engagement_posts=pending_posts,
    )


@router.post("/generate-post", response_model=GeneratePostResponse)
async def generate_post(
    request: GeneratePostRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    topic = await db.get(ContentTopic, request.topic_id)
    if not topic or topic.user_id != current_user.id:
        raise HTTPException(404, "Topic not found")

    stories = await db.execute(
        select(UserStory)
        .where(UserStory.user_id == current_user.id)
        .order_by(UserStory.used_count.asc())
        .limit(3)
    )
    stories_list = list(stories.scalars().all())

    settings = await get_or_create_settings(db, current_user.id)
    profile = await get_user_profile(db, current_user.id)

    draft = await generate_linkedin_post(
        topic_title=topic.topic_title,
        category=topic.category,
        angle=topic.angle,
        profile=profile,
        stories=stories_list,
        avoid_specific_numbers=settings.avoid_specific_numbers,
    )

    if draft is None:
        raise HTTPException(503, "AI generation failed")

    return GeneratePostResponse(
        draft_text=draft,
        topic_title=topic.topic_title,
        category=topic.category,
        suggested_creative=topic.suggested_creative,
        character_count=len(draft),
    )


@router.post("/regenerate", response_model=GeneratePostResponse)
async def regenerate_post(
    request: RegenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    topic = await db.get(ContentTopic, request.topic_id)
    if not topic or topic.user_id != current_user.id:
        raise HTTPException(404, "Topic not found")

    stories = await db.execute(
        select(UserStory)
        .where(UserStory.user_id == current_user.id)
        .order_by(UserStory.used_count.asc())
        .limit(3)
    )
    settings = await get_or_create_settings(db, current_user.id)
    profile = await get_user_profile(db, current_user.id)

    draft = await generate_linkedin_post(
        topic_title=topic.topic_title,
        category=topic.category,
        angle=topic.angle,
        profile=profile,
        stories=list(stories.scalars().all()),
        avoid_specific_numbers=settings.avoid_specific_numbers,
        instruction=request.instruction,
    )

    if draft is None:
        raise HTTPException(503, "AI generation failed")

    return GeneratePostResponse(
        draft_text=draft,
        topic_title=topic.topic_title,
        category=topic.category,
        suggested_creative=topic.suggested_creative,
        character_count=len(draft),
    )


@router.post("/mark-posted")
async def mark_posted(
    request: MarkPostedRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)

    post = ContentPost(
        user_id=current_user.id,
        post_text=request.post_text,
        topic_title=request.topic_title,
        topic_category=request.category,
        posted_at=now,
        day_of_week=now.weekday(),
        time_of_day=get_time_of_day(now),
        had_image=request.had_image,
        had_carousel=request.had_carousel,
        generated_by_system=True,
    )
    db.add(post)

    if request.topic_id:
        topic = await db.get(ContentTopic, request.topic_id)
        if topic and topic.user_id == current_user.id:
            topic.status = "used"

    await db.commit()
    await db.refresh(post)

    return {
        "status": "posted",
        "post_id": str(post.id),
        "engagement_reminder_at": (now + timedelta(hours=48)).isoformat(),
    }


@router.post("/engagement")
async def record_engagement(
    request: RecordEngagementRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await db.get(ContentPost, request.post_id)
    if not post or post.user_id != current_user.id:
        raise HTTPException(404, "Post not found")

    if request.impressions is not None:
        post.impressions = request.impressions
    if request.reactions is not None:
        post.reactions = request.reactions
    if request.comments is not None:
        post.comments = request.comments
    post.engagement_recorded_at = datetime.now(timezone.utc)

    await db.commit()

    return {"status": "recorded"}


@router.get("/history")
async def get_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 20,
    category: Optional[str] = None,
):
    query = select(ContentPost).where(ContentPost.user_id == current_user.id)

    if category:
        query = query.where(ContentPost.topic_category == category)

    query = query.order_by(ContentPost.posted_at.desc()).limit(limit)

    result = await db.execute(query)
    posts = result.scalars().all()

    insights = await calculate_insights(db, current_user.id)

    return {
        "posts": [
            {
                "id": str(p.id),
                "post_text": p.post_text,
                "topic_title": p.topic_title,
                "category": p.topic_category,
                "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                "impressions": p.impressions,
                "reactions": p.reactions,
                "comments": p.comments,
                "had_image": p.had_image,
                "had_carousel": p.had_carousel,
            }
            for p in posts
        ],
        "insights": insights,
    }


@router.post("/topics/refresh")
async def refresh_topics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = await get_or_create_settings(db, current_user.id)
    topics = await generate_topics(db, current_user, settings.categories, force_new=True)
    return {"topics": [TopicOut.model_validate(t) for t in topics]}


@router.post("/topics/{topic_id}/dismiss")
async def dismiss_topic(
    topic_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    topic = await db.get(ContentTopic, topic_id)
    if not topic or topic.user_id != current_user.id:
        raise HTTPException(404, "Topic not found")
    topic.status = "dismissed"
    await db.commit()
    return {"status": "dismissed"}


@router.post("/topics/custom")
async def add_custom_topic(
    request: AddCustomTopicRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    topic = ContentTopic(
        user_id=current_user.id,
        topic_title=request.topic_title,
        category=request.category,
        angle="custom",
        suggested_creative="text",
        status="available",
    )
    db.add(topic)
    await db.commit()
    await db.refresh(topic)
    return TopicOut.model_validate(topic)


@router.get("/stories/today-prompt")
async def get_today_prompt(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prompt = await get_todays_prompt(db, current_user.id)
    return prompt


@router.post("/stories/dismiss-prompt")
async def dismiss_prompt(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = datetime.now(timezone.utc).date()
    await db.execute(
        update(StoryPromptShown)
        .where(StoryPromptShown.user_id == current_user.id)
        .where(func.date(StoryPromptShown.shown_at) == today)
        .values(dismissed=True)
    )
    await db.commit()
    return {"status": "dismissed"}


@router.post("/stories")
async def save_story(
    request: SaveStoryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    story = UserStory(
        user_id=current_user.id,
        prompt_question=request.prompt_question,
        story_text=request.story_text,
        company_context=request.company_context,
        theme=request.theme,
    )
    db.add(story)

    today = datetime.now(timezone.utc).date()
    await db.execute(
        update(StoryPromptShown)
        .where(StoryPromptShown.user_id == current_user.id)
        .where(func.date(StoryPromptShown.shown_at) == today)
        .values(answered=True)
    )

    await db.commit()
    count = await get_stories_count(db, current_user.id)
    return {"status": "saved", "stories_count": count}


@router.get("/stories")
async def list_stories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserStory)
        .where(UserStory.user_id == current_user.id)
        .order_by(UserStory.created_at.desc())
    )
    return {
        "stories": [
            {
                "id": str(s.id),
                "prompt_question": s.prompt_question,
                "story_text": s.story_text,
                "company_context": s.company_context,
                "theme": s.theme,
                "used_count": s.used_count,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in result.scalars().all()
        ]
    }
