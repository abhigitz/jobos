"""Add followup_date to jobs for D11 Followup Manager.

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-02-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "h8c9d0e1f2g3"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("followup_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "followup_date")
