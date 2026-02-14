"""Add linkedin_url and phone to profile_dna for cover letter generation

Revision ID: o5f6g7h8i9j0
Revises: n4e5f6g7h8i9
Create Date: 2026-02-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o5f6g7h8i9j0"
down_revision: Union[str, Sequence[str], None] = "n4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profile_dna", sa.Column("linkedin_url", sa.String(1000), nullable=True))
    op.add_column("profile_dna", sa.Column("phone", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("profile_dna", "phone")
    op.drop_column("profile_dna", "linkedin_url")
