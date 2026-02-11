"""add_daily_log_fields_and_job_apply_type

Revision ID: 260827cb3641
Revises: fix_refresh_tz
Create Date: 2026-02-11 10:08:11.749783

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '260827cb3641'
down_revision: Union[str, Sequence[str], None] = 'fix_refresh_tz'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new fields to daily_log table
    op.add_column('daily_log', sa.Column('energy_level', sa.Integer(), nullable=True))
    op.add_column('daily_log', sa.Column('mood', sa.String(length=50), nullable=True))
    op.add_column('daily_log', sa.Column('notes', sa.Text(), nullable=True))
    
    # Add check constraint for energy_level
    op.create_check_constraint(
        'ck_daily_log_energy_range',
        'daily_log',
        'energy_level BETWEEN 1 AND 5'
    )
    
    # Add apply_type column to jobs table
    op.add_column('jobs', sa.Column('apply_type', sa.String(length=10), nullable=True))
    
    # Update job status constraint to include new statuses
    op.drop_constraint('ck_jobs_status_valid', 'jobs', type_='check')
    op.create_check_constraint(
        'ck_jobs_status_valid',
        'jobs',
        "status IN ('Analyzed', 'Applied', 'Screening', 'Interview Scheduled', 'Interview Done', 'Offer', 'Rejected', 'Withdrawn', 'Ghosted')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove check constraints
    op.drop_constraint('ck_daily_log_energy_range', 'daily_log', type_='check')
    op.drop_constraint('ck_jobs_status_valid', 'jobs', type_='check')
    
    # Remove columns from daily_log
    op.drop_column('daily_log', 'notes')
    op.drop_column('daily_log', 'mood')
    op.drop_column('daily_log', 'energy_level')
    
    # Remove column from jobs
    op.drop_column('jobs', 'apply_type')
    
    # Restore old job status constraint
    op.create_check_constraint(
        'ck_jobs_status_valid',
        'jobs',
        "status IN ('Saved', 'Discovered', 'Analyzed', 'Applied', 'Screening', 'Interview_Scheduled', 'Interview_Done', 'Offer', 'Rejected', 'Withdrawn')"
    )
