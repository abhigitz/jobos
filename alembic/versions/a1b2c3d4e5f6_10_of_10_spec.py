"""10 of 10 spec: interviews, activity_log, new columns

Revision ID: a1b2c3d4e5f6
Revises: 260827cb3641
Create Date: 2026-02-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '260827cb3641'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New table: interviews ---
    op.create_table(
        'interviews',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('interview_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('round', sa.String(100), nullable=False, server_default='Phone Screen'),
        sa.Column('interviewer_name', sa.String(255), nullable=True),
        sa.Column('interviewer_role', sa.String(255), nullable=True),
        sa.Column('interviewer_linkedin', sa.String(500), nullable=True),
        sa.Column('status', sa.String(50), server_default='Scheduled'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('questions_asked', sa.Text(), nullable=True),
        sa.Column('went_well', sa.Text(), nullable=True),
        sa.Column('to_improve', sa.Text(), nullable=True),
        sa.Column('next_steps', sa.Text(), nullable=True),
        sa.Column('prep_content', sa.Text(), nullable=True),
        sa.Column('prep_generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('Scheduled', 'Completed', 'Cancelled', 'No-show')", name='ck_interviews_status_valid'),
        sa.CheckConstraint('rating BETWEEN 1 AND 10', name='ck_interviews_rating_range'),
    )
    op.create_index('idx_interviews_user_date', 'interviews', ['user_id', 'interview_date'])
    op.create_index('idx_interviews_job', 'interviews', ['job_id'])

    # --- New table: activity_log ---
    op.create_table(
        'activity_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('related_job_id', UUID(as_uuid=True), sa.ForeignKey('jobs.id'), nullable=True),
        sa.Column('related_contact_id', UUID(as_uuid=True), sa.ForeignKey('contacts.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_activity_user_time', 'activity_log', ['user_id', sa.text('created_at DESC')])

    # --- Modify companies: add is_excluded ---
    op.add_column('companies', sa.Column('is_excluded', sa.Boolean(), server_default=sa.text('false'), nullable=True))

    # --- Modify contacts: add new columns if missing ---
    # follow_up_date and referral_status already exist; add last_outreach_date and outreach_notes
    op.add_column('contacts', sa.Column('last_outreach_date', sa.Date(), nullable=True))
    op.add_column('contacts', sa.Column('outreach_notes', sa.Text(), nullable=True))

    # --- Modify jobs: add followup tracking columns ---
    op.add_column('jobs', sa.Column('last_followup_date', sa.Date(), nullable=True))
    op.add_column('jobs', sa.Column('followup_count', sa.Integer(), server_default='0', nullable=True))

    # --- Seed excluded companies ---
    op.execute("UPDATE companies SET is_excluded = true WHERE name IN ('Swiggy', 'Zomato', 'Licious')")


def downgrade() -> None:
    # Remove job columns
    op.drop_column('jobs', 'followup_count')
    op.drop_column('jobs', 'last_followup_date')

    # Remove contact columns
    op.drop_column('contacts', 'outreach_notes')
    op.drop_column('contacts', 'last_outreach_date')

    # Remove company column
    op.drop_column('companies', 'is_excluded')

    # Drop tables
    op.drop_index('idx_activity_user_time', table_name='activity_log')
    op.drop_table('activity_log')
    op.drop_index('idx_interviews_job', table_name='interviews')
    op.drop_index('idx_interviews_user_date', table_name='interviews')
    op.drop_table('interviews')
