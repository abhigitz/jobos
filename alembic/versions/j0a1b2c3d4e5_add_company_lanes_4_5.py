"""Add company lanes 4 and 5 (early-stage, pre-seed).

Revision ID: j0a1b2c3d4e5
Revises: i9d0e1f2g3h4
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op

revision: str = "j0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "i9d0e1f2g3h4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE companies DROP CONSTRAINT ck_companies_lane_valid")
    op.execute(
        "ALTER TABLE companies ADD CONSTRAINT ck_companies_lane_valid "
        "CHECK (lane IN (1, 2, 3, 4, 5))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE companies DROP CONSTRAINT ck_companies_lane_valid")
    op.execute(
        "ALTER TABLE companies ADD CONSTRAINT ck_companies_lane_valid "
        "CHECK (lane IN (1, 2, 3))"
    )
