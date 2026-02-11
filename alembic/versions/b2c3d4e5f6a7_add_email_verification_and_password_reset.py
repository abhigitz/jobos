"""add email verification and password reset tokens

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-11 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- New table: email_verification_tokens ---
    op.create_table(
        'email_verification_tokens',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(255), unique=True, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_email_verification_tokens_token', 'email_verification_tokens', ['token'], unique=True)
    op.create_index('idx_email_verification_tokens_user_id', 'email_verification_tokens', ['user_id'])

    # --- New table: password_reset_tokens ---
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token', sa.String(255), unique=True, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('idx_password_reset_tokens_token', 'password_reset_tokens', ['token'], unique=True)
    op.create_index('idx_password_reset_tokens_user_id', 'password_reset_tokens', ['user_id'])

    # --- Add email_verified column to users ---
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False))

    # Backfill: mark existing users as verified so the seeded user can still log in
    op.execute("UPDATE users SET email_verified = TRUE WHERE email_verified IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    # Remove email_verified column
    op.drop_column('users', 'email_verified')

    # Drop password_reset_tokens
    op.drop_index('idx_password_reset_tokens_user_id', table_name='password_reset_tokens')
    op.drop_index('idx_password_reset_tokens_token', table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')

    # Drop email_verification_tokens
    op.drop_index('idx_email_verification_tokens_user_id', table_name='email_verification_tokens')
    op.drop_index('idx_email_verification_tokens_token', table_name='email_verification_tokens')
    op.drop_table('email_verification_tokens')

