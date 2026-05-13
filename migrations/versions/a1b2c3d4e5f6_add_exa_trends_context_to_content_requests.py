"""add exa_trends_context to content_requests

Revision ID: a1b2c3d4e5f6
Revises: f3a4b5c6d7e8
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'content_requests',
        sa.Column(
            'exa_trends_context',
            sa.Text(),
            nullable=True,
            comment='Contexto de mercado injetado pelo Exa Search (Story 13.2) — auditoria e futura exibição',
        )
    )


def downgrade() -> None:
    op.drop_column('content_requests', 'exa_trends_context')
