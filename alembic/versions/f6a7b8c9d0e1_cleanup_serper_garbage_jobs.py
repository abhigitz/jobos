"""Cleanup garbage jobs from Serper source.

Serper /search returns Google result pages, not individual job postings.
These polluted the pipeline and need to be removed.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-02-12 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f6a7b8c9d0e1'
down_revision: str = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Delete activity_log entries referencing serper jobs (FK: activity_log.related_job_id)
    op.execute(
        "DELETE FROM activity_log WHERE related_job_id IN "
        "(SELECT id FROM jobs WHERE source_portal = 'serper')"
    )
    # 2. Delete scout_results from serper so they don't block future dedup
    op.execute("DELETE FROM scout_results WHERE source = 'serper'")
    # 3. Now safe to delete the garbage jobs themselves
    op.execute("DELETE FROM jobs WHERE source_portal = 'serper'")


def downgrade() -> None:
    # Data deletion is not reversible
    pass
