"""company_researches_table

Revision ID: p6g7h8i9j0k1
Revises: o5f6g7h8i9j0
Create Date: 2026-02-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "p6g7h8i9j0k1"
down_revision: Union[str, Sequence[str], None] = "o5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_researches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("custom_questions", sa.Text(), nullable=True),
        sa.Column("research_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_researches_user_id", "company_researches", ["user_id"])
    op.create_index("ix_company_researches_created_at", "company_researches", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_company_researches_created_at", table_name="company_researches")
    op.drop_index("ix_company_researches_user_id", table_name="company_researches")
    op.drop_table("company_researches")
