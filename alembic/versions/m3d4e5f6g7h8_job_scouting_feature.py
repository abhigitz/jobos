"""Job scouting feature -- scouted_jobs, user_scout_preferences, user_scouted_jobs, company_career_sources

Revision ID: m3d4e5f6g7h8
Revises: l2c3d4e5f6g7
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID


revision: str = "m3d4e5f6g7h8"
down_revision: Union[str, Sequence[str], None] = "l2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scouted_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("dedup_hash", sa.String(64), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("company_name_normalized", sa.String(255), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_is_estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=True),
        sa.Column("apply_url", sa.String(2000), nullable=True),
        sa.Column("posted_date", sa.Date(), nullable=True),
        sa.Column("scouted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("inactive_reason", sa.String(50), nullable=True),
        sa.Column("matched_company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("raw_json", JSONB, nullable=True),
        sa.Column("search_query", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("dedup_hash", name="uq_scouted_jobs_dedup_hash"),
    )
    op.create_index("idx_scouted_jobs_dedup", "scouted_jobs", ["dedup_hash"])
    op.create_index(
        "idx_scouted_jobs_active",
        "scouted_jobs",
        ["is_active", "posted_date"],
        postgresql_ops={"posted_date": "DESC"},
    )
    op.create_index("idx_scouted_jobs_company", "scouted_jobs", ["company_name_normalized"])
    op.create_index(
        "idx_scouted_jobs_source",
        "scouted_jobs",
        ["source", "scouted_at"],
        postgresql_ops={"scouted_at": "DESC"},
    )

    op.create_table(
        "user_scout_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_roles", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("role_keywords", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("target_locations", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("location_flexibility", sa.String(20), nullable=False, server_default=sa.text("'preferred'")),
        sa.Column("target_company_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'::uuid[]")),
        sa.Column("excluded_company_ids", ARRAY(UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'::uuid[]")),
        sa.Column("target_industries", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("excluded_industries", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("company_stages", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("min_salary", sa.Integer(), nullable=True),
        sa.Column("salary_flexibility", sa.String(20), nullable=False, server_default=sa.text("'flexible'")),
        sa.Column("min_score", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("learned_boosts", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("learned_penalties", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("synced_from_profile_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_user_scout_preferences_user_id"),
    )

    op.create_table(
        "user_scouted_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scouted_job_id", UUID(as_uuid=True), sa.ForeignKey("scouted_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relevance_score", sa.Integer(), nullable=False),
        sa.Column("score_breakdown", JSONB, nullable=True),
        sa.Column("match_reasons", ARRAY(sa.Text()), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'new'")),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismiss_reason", sa.String(50), nullable=True),
        sa.Column("pipeline_job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("added_to_pipeline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "scouted_job_id", name="uq_user_scouted_jobs_user_scouted_job"),
    )
    op.create_index(
        "idx_user_scouted_user_status",
        "user_scouted_jobs",
        ["user_id", "status", "matched_at"],
        postgresql_ops={"matched_at": "DESC"},
    )
    op.execute(
        "CREATE INDEX idx_user_scouted_score ON user_scouted_jobs(user_id, relevance_score DESC) WHERE status = 'new'"
    )
    op.create_index("idx_user_scouted_job", "user_scouted_jobs", ["scouted_job_id"])

    op.create_table(
        "company_career_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("careers_url", sa.String(2000), nullable=False),
        sa.Column("api_endpoint", sa.String(2000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scrape_frequency_hours", sa.Integer(), nullable=False, server_default=sa.text("24")),
        sa.Column("scrape_config", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "source_type", name="uq_company_career_sources_company_source"),
    )


def downgrade() -> None:
    op.drop_table("company_career_sources")
    op.drop_index("idx_user_scouted_job", table_name="user_scouted_jobs")
    op.drop_index("idx_user_scouted_score", table_name="user_scouted_jobs")
    op.drop_index("idx_user_scouted_user_status", table_name="user_scouted_jobs")
    op.drop_table("user_scouted_jobs")
    op.drop_table("user_scout_preferences")
    op.drop_index("idx_scouted_jobs_source", table_name="scouted_jobs")
    op.drop_index("idx_scouted_jobs_company", table_name="scouted_jobs")
    op.drop_index("idx_scouted_jobs_active", table_name="scouted_jobs")
    op.drop_index("idx_scouted_jobs_dedup", table_name="scouted_jobs")
    op.drop_table("scouted_jobs")
