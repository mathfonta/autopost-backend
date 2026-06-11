"""add marketing_intent to content_requests

Revision ID: d3e4f5a6b7c8
Revises: c3d4e5f6a7b8
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'content_requests',
        sa.Column('marketing_intent', sa.String(50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('content_requests', 'marketing_intent')
