"""Jobs status overhaul and notes JSONB conversion

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add new columns
    op.add_column('jobs', sa.Column('application_channel', sa.String(50), nullable=True))
    op.add_column('jobs', sa.Column('closed_reason', sa.String(50), nullable=True))

    # Step 2: Drop the old CHECK constraint first
    op.drop_constraint('ck_jobs_status_valid', 'jobs', type_='check')

    # Step 3: Migrate status data
    # Set closed_reason from old terminal statuses
    op.execute("UPDATE jobs SET closed_reason = 'Rejected' WHERE status = 'Rejected'")
    op.execute("UPDATE jobs SET closed_reason = 'Withdrawn' WHERE status = 'Withdrawn'")
    op.execute("UPDATE jobs SET closed_reason = 'Ghosted' WHERE status = 'Ghosted'")
    # Map old statuses to new statuses
    op.execute("UPDATE jobs SET status = 'Closed' WHERE status IN ('Rejected', 'Withdrawn', 'Ghosted')")
    op.execute("UPDATE jobs SET status = 'Tracking' WHERE status = 'Analyzed'")
    op.execute("UPDATE jobs SET status = 'Applied' WHERE status = 'Screening'")
    op.execute("UPDATE jobs SET status = 'Interview' WHERE status IN ('Interview Scheduled', 'Interview Done')")

    # Step 4: Add new CHECK constraint
    op.create_check_constraint(
        'ck_jobs_status_valid',
        'jobs',
        "status IN ('Tracking', 'Applied', 'Interview', 'Offer', 'Closed')"
    )

    # Step 5: Convert notes from Text to JSONB
    op.execute("""
        ALTER TABLE jobs ALTER COLUMN notes TYPE JSONB USING
          CASE
            WHEN notes IS NULL THEN '[]'::jsonb
            WHEN notes = '' THEN '[]'::jsonb
            ELSE jsonb_build_array(jsonb_build_object('text', notes, 'created_at', now()::text))
          END
    """)
    op.execute("ALTER TABLE jobs ALTER COLUMN notes SET DEFAULT '[]'::jsonb")


def downgrade() -> None:
    # Step 1: Remove notes default, convert JSONB back to Text
    op.execute("ALTER TABLE jobs ALTER COLUMN notes DROP DEFAULT")
    op.execute("""
        ALTER TABLE jobs ALTER COLUMN notes TYPE TEXT USING
          CASE
            WHEN notes IS NULL THEN NULL
            WHEN jsonb_array_length(notes) = 0 THEN NULL
            ELSE notes->0->>'text'
          END
    """)

    # Step 2: Drop new CHECK, reverse status migration, add back old CHECK
    op.drop_constraint('ck_jobs_status_valid', 'jobs', type_='check')

    # Reverse status migration
    op.execute("UPDATE jobs SET status = 'Analyzed' WHERE status = 'Tracking'")
    op.execute("UPDATE jobs SET status = 'Interview Scheduled' WHERE status = 'Interview'")
    # Use closed_reason to restore original terminal statuses where possible
    op.execute("UPDATE jobs SET status = closed_reason WHERE status = 'Closed' AND closed_reason IN ('Rejected', 'Withdrawn', 'Ghosted')")
    op.execute("UPDATE jobs SET status = 'Rejected' WHERE status = 'Closed'")

    op.create_check_constraint(
        'ck_jobs_status_valid',
        'jobs',
        "status IN ('Analyzed', 'Applied', 'Screening', 'Interview Scheduled', 'Interview Done', 'Offer', 'Rejected', 'Withdrawn', 'Ghosted')"
    )

    # Step 3: Drop new columns
    op.drop_column('jobs', 'closed_reason')
    op.drop_column('jobs', 'application_channel')
