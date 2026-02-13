"""content_studio_v2_tables

Revision ID: l2c3d4e5f6g7
Revises: k1b2c3d4e5f6
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "l2c3d4e5f6g7"
down_revision: Union[str, Sequence[str], None] = "k1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_posts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("post_text", sa.Text(), nullable=False),
        sa.Column("topic_title", sa.Text(), nullable=True),
        sa.Column("topic_category", sa.String(length=50), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("time_of_day", sa.String(length=20), nullable=True),
        sa.Column("impressions", sa.Integer(), nullable=True),
        sa.Column("reactions", sa.Integer(), nullable=True),
        sa.Column("comments", sa.Integer(), nullable=True),
        sa.Column("engagement_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("had_image", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("had_carousel", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generated_by_system", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_posts_user_id", "content_posts", ["user_id"])
    op.create_index("ix_content_posts_posted_at", "content_posts", ["posted_at"])

    op.create_table(
        "user_stories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("prompt_question", sa.Text(), nullable=True),
        sa.Column("story_text", sa.Text(), nullable=False),
        sa.Column("company_context", sa.String(length=100), nullable=True),
        sa.Column("theme", sa.String(length=50), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_stories_user_id", "user_stories", ["user_id"])

    op.create_table(
        "content_topics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("topic_title", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("angle", sa.String(length=50), nullable=True),
        sa.Column("suggested_creative", sa.String(length=20), nullable=False, server_default=sa.text("'text'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'available'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_topics_user_id_status", "content_topics", ["user_id", "status"])

    op.create_table(
        "story_prompts_shown",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("shown_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("answered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_story_prompts_user_id", "story_prompts_shown", ["user_id"])

    op.create_table(
        "user_content_settings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "categories",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"Growth\", \"Career\", \"Leadership\", \"GenAI\", \"Industry\", \"Personal\"]'::jsonb"),
        ),
        sa.Column("weekly_post_goal", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("avoid_specific_numbers", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_content_settings")
    op.drop_index("ix_story_prompts_user_id", table_name="story_prompts_shown")
    op.drop_table("story_prompts_shown")
    op.drop_index("ix_content_topics_user_id_status", table_name="content_topics")
    op.drop_table("content_topics")
    op.drop_index("ix_user_stories_user_id", table_name="user_stories")
    op.drop_table("user_stories")
    op.drop_index("ix_content_posts_posted_at", table_name="content_posts")
    op.drop_index("ix_content_posts_user_id", table_name="content_posts")
    op.drop_table("content_posts")
