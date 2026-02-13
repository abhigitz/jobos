"""add_performance_indexes

Revision ID: k1b2c3d4e5f6
Revises: j0a1b2c3d4e5
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op

revision: str = "k1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "j0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Activity log queries
    op.create_index("ix_activity_log_user_created", "activity_log", ["user_id", "created_at"])

    # Job queries
    op.create_index("ix_jobs_user_status", "jobs", ["user_id", "status"])
    op.create_index("ix_jobs_followup_date", "jobs", ["followup_date"])
    op.create_index("ix_jobs_user_applied", "jobs", ["user_id", "applied_date"])

    # Company queries
    op.create_index("ix_companies_user_id", "companies", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_activity_log_user_created", table_name="activity_log")
    op.drop_index("ix_jobs_user_status", table_name="jobs")
    op.drop_index("ix_jobs_followup_date", table_name="jobs")
    op.drop_index("ix_jobs_user_applied", table_name="jobs")
    op.drop_index("ix_companies_user_id", table_name="companies")
