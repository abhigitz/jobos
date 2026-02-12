"""JD Analyzer redesign Phase A - new columns, pg_trgm, closed_reason cleanup

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Enable pg_trgm extension for fuzzy company search
    # Wrapped in try/except equivalent -- IF NOT EXISTS handles gracefully
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Step 2: Add new columns to jobs
    op.add_column('jobs', sa.Column('fit_reasoning', sa.Text(), nullable=True))
    op.add_column('jobs', sa.Column('salary_range', sa.String(100), nullable=True))

    # Step 3: Create trigram GIN index on companies.name for fuzzy search
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_companies_name_trgm ON companies USING gin (name gin_trgm_ops)"
    )

    # Step 4: Clean up closed_reason values
    # Withdrawn and No Response become Dropped
    op.execute("UPDATE jobs SET closed_reason = 'Dropped' WHERE closed_reason IN ('Withdrawn', 'No Response')")


def downgrade() -> None:
    op.execute("UPDATE jobs SET closed_reason = 'No Response' WHERE closed_reason = 'Dropped'")
    op.execute("DROP INDEX IF EXISTS ix_companies_name_trgm")
    op.drop_column('jobs', 'salary_range')
    op.drop_column('jobs', 'fit_reasoning')
