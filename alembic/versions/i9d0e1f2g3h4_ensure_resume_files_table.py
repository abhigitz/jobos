"""Ensure resume_files table exists (fix for production DBs where migration was skipped).

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op


revision: str = "i9d0e1f2g3h4"
down_revision: Union[str, Sequence[str], None] = "h8c9d0e1f2g3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS resume_files (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        filename VARCHAR(255) NOT NULL,
        file_content BYTEA NOT NULL,
        file_size INTEGER NOT NULL,
        mime_type VARCHAR(100) DEFAULT 'application/pdf',
        version INTEGER DEFAULT 1,
        is_primary BOOLEAN DEFAULT false,
        extracted_text TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
    )
    """)


def downgrade() -> None:
    op.drop_table("resume_files", if_exists=True)
