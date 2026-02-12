"""standardize_closed_reason_values

Revision ID: c3d4e5f6a7b9
Revises: b2c3d4e5f6a8
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c3d4e5f6a7b9'
down_revision: str = 'b2c3d4e5f6a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE jobs SET closed_reason = 'Dropped' WHERE closed_reason = 'No Response'")
    op.execute("UPDATE jobs SET closed_reason = 'Not Interested' WHERE closed_reason = 'Withdrawn'")


def downgrade() -> None:
    op.execute("UPDATE jobs SET closed_reason = 'No Response' WHERE closed_reason = 'Dropped'")
    op.execute("UPDATE jobs SET closed_reason = 'Withdrawn' WHERE closed_reason = 'Not Interested'")
