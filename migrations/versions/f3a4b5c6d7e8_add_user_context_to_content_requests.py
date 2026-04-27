"""add user_context to content_requests

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'content_requests',
        sa.Column('user_context', sa.Text(), nullable=True,
                  comment='Contexto opcional digitado pelo cliente antes do upload')
    )


def downgrade() -> None:
    op.drop_column('content_requests', 'user_context')
