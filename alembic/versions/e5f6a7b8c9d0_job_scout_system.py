"""Job Scout system -- scout_results table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-02-12 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scout_results',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source', sa.String(50), nullable=False),
        sa.Column('source_url', sa.String(2000), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('company_name', sa.String(500), nullable=False),
        sa.Column('location', sa.String(500), nullable=True),
        sa.Column('snippet', sa.Text(), nullable=True),
        sa.Column('salary_raw', sa.String(200), nullable=True),
        sa.Column('posted_date_raw', sa.String(100), nullable=True),
        sa.Column('normalized_data', JSONB, nullable=True),
        sa.Column('fit_score', sa.Float(), nullable=True),
        sa.Column('b2c_validated', sa.Boolean(), default=False),
        sa.Column('ai_reasoning', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='new'),
        sa.Column('promoted_job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('scout_run_id', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('new', 'reviewed', 'promoted', 'dismissed')",
            name='ck_scout_results_status_valid',
        ),
    )
    # Index for fast lookups by user + status
    op.create_index('ix_scout_results_user_status', 'scout_results', ['user_id', 'status'])
    # Index for dedup by source_url
    op.create_index('ix_scout_results_source_url', 'scout_results', ['source_url'])


def downgrade() -> None:
    op.drop_index('ix_scout_results_source_url')
    op.drop_index('ix_scout_results_user_status')
    op.drop_table('scout_results')
