"""add_analysis_fields_to_jobs

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2c3d4e5f6a8'
down_revision: str = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('resume_suggestions', postgresql.JSONB(), nullable=True))
    op.add_column('jobs', sa.Column('interview_angle', sa.Text(), nullable=True))
    op.add_column('jobs', sa.Column('b2c_check', sa.Boolean(), nullable=True))
    op.add_column('jobs', sa.Column('b2c_reason', sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'b2c_reason')
    op.drop_column('jobs', 'b2c_check')
    op.drop_column('jobs', 'interview_angle')
    op.drop_column('jobs', 'resume_suggestions')
