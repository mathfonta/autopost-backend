"""add caption variants to content_requests

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'content_requests',
        sa.Column('caption_long', sa.Text(), nullable=True,
                  comment='Variação longa gerada pelo Copywriter (até 400 chars)')
    )
    op.add_column(
        'content_requests',
        sa.Column('caption_short', sa.String(150), nullable=True,
                  comment='Variação curta gerada pelo Copywriter (até 150 chars)')
    )
    op.add_column(
        'content_requests',
        sa.Column('caption_stories', sa.String(100), nullable=True,
                  comment='Variação Stories gerada pelo Copywriter (até 100 chars)')
    )
    op.add_column(
        'content_requests',
        sa.Column(
            'caption_selected',
            sa.String(10),
            nullable=True,
            server_default='long',
            comment='Variação escolhida pelo usuário: long | short | stories',
        )
    )
    op.create_check_constraint(
        'ck_content_requests_caption_selected',
        'content_requests',
        "caption_selected IN ('long', 'short', 'stories')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_content_requests_caption_selected', 'content_requests', type_='check')
    op.drop_column('content_requests', 'caption_selected')
    op.drop_column('content_requests', 'caption_stories')
    op.drop_column('content_requests', 'caption_short')
    op.drop_column('content_requests', 'caption_long')
