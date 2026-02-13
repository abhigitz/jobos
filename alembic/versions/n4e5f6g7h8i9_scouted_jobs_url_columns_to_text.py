"""Scouted jobs: change source_url, external_id, apply_url from VARCHAR to TEXT

Revision ID: n4e5f6g7h8i9
Revises: m3d4e5f6g7h8
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op


revision: str = "n4e5f6g7h8i9"
down_revision: Union[str, Sequence[str], None] = "m3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE scouted_jobs ALTER COLUMN source_url TYPE TEXT")
    op.execute("ALTER TABLE scouted_jobs ALTER COLUMN external_id TYPE TEXT")
    op.execute("ALTER TABLE scouted_jobs ALTER COLUMN apply_url TYPE TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE scouted_jobs ALTER COLUMN source_url TYPE VARCHAR(2000)")
    op.execute("ALTER TABLE scouted_jobs ALTER COLUMN external_id TYPE VARCHAR(255)")
    op.execute("ALTER TABLE scouted_jobs ALTER COLUMN apply_url TYPE VARCHAR(2000)")
