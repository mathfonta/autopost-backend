"""create weekly_context table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-12 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'weekly_context',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('week_of', sa.Date(), nullable=False),
        sa.Column('segment', sa.String(100), nullable=False),
        sa.Column('raw_snippets', JSONB(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('hashtags', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_weekly_context_week_of', 'weekly_context', ['week_of'])
    op.create_index('ix_weekly_context_segment', 'weekly_context', ['segment'])


def downgrade() -> None:
    op.drop_index('ix_weekly_context_segment', table_name='weekly_context')
    op.drop_index('ix_weekly_context_week_of', table_name='weekly_context')
    op.drop_table('weekly_context')
