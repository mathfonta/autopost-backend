"""add strategy to content_requests

Revision ID: a3b4c5d6e7f8
Revises: f3a4b5c6d7e8
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'content_requests',
        sa.Column('strategy', sa.String(50), nullable=True,
                  comment='Sub-estratégia Instagram: prova_social | antes_depois | hook_choque | enquete | etc.')
    )


def downgrade() -> None:
    op.drop_column('content_requests', 'strategy')
