from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic_title: str
    category: str
    angle: Optional[str] = None
    suggested_creative: str = "text"


class StoryPromptOut(BaseModel):
    prompt_text: str
    can_dismiss: bool = True


class ContentStudioHome(BaseModel):
    topics: List[TopicOut]
    weekly_streak: int
    weekly_goal: int
    best_posting_time: Optional[str] = None
    story_prompt: Optional[StoryPromptOut] = None
    stories_count: int
    pending_engagement_posts: List[dict]


class GeneratePostRequest(BaseModel):
    topic_id: UUID


class GeneratePostResponse(BaseModel):
    draft_text: str
    topic_title: str
    category: str
    suggested_creative: str
    character_count: int


class RegenerateRequest(BaseModel):
    topic_id: UUID
    instruction: Optional[str] = None


class MarkPostedRequest(BaseModel):
    post_text: str
    topic_id: Optional[UUID] = None
    topic_title: Optional[str] = None
    category: Optional[str] = None
    had_image: bool = False
    had_carousel: bool = False


class RecordEngagementRequest(BaseModel):
    post_id: UUID
    impressions: Optional[int] = None
    reactions: Optional[int] = None
    comments: Optional[int] = None


class SaveStoryRequest(BaseModel):
    prompt_question: str
    story_text: str
    company_context: Optional[str] = None
    theme: Optional[str] = None


class AddCustomTopicRequest(BaseModel):
    topic_title: str
    category: str
