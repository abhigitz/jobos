"""fix refresh_token expires_at timezone

Revision ID: fix_refresh_tz
Revises: dec629142039
Create Date: 2026-02-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fix_refresh_tz'
down_revision: Union[str, Sequence[str], None] = 'dec629142039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'refresh_tokens',
        'expires_at',
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        'refresh_tokens',
        'expires_at',
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
