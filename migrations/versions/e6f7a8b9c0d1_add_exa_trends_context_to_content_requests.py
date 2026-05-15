"""add exa_trends_context to content_requests

Revision ID: e6f7a8b9c0d1
Revises: d2e3f4a5b6c7
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
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
