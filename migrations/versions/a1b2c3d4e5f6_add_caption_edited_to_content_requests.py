"""add caption_edited to content_requests

Revision ID: a1b2c3d4e5f6
Revises: d5e2f9a3c1b7
Create Date: 2026-04-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd5e2f9a3c1b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'content_requests',
        sa.Column(
            'caption_edited',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='True quando o cliente editou a legenda gerada pelo agente',
        )
    )


def downgrade() -> None:
    op.drop_column('content_requests', 'caption_edited')
