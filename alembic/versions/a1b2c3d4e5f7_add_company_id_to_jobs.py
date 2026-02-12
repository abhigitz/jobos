"""add_company_id_to_jobs

Revision ID: a1b2c3d4e5f7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: str = 'g7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id', ondelete='SET NULL'), nullable=True))
    op.create_index('idx_jobs_company_id', 'jobs', ['company_id'])
    op.alter_column('companies', 'lane', nullable=True)


def downgrade() -> None:
    op.alter_column('companies', 'lane', nullable=False)
    op.drop_index('idx_jobs_company_id', table_name='jobs')
    op.drop_column('jobs', 'company_id')
