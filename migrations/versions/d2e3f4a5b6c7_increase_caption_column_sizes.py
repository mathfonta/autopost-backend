"""increase caption_short and caption_stories column sizes

Revision ID: d2e3f4a5b6c7
Revises: b49823625e1a
Create Date: 2026-05-11 00:00:00.000000

caption_short era VARCHAR(150) mas MAX_CAPTION_SHORT_CHARS foi aumentado para 300.
caption_stories era VARCHAR(100) mas MAX_CAPTION_STORIES_CHARS foi aumentado para 150.
Ambas convertidas para TEXT para não precisar de migrations futuras ao ajustar limites.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'b49823625e1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'content_requests',
        'caption_short',
        type_=sa.Text(),
        existing_type=sa.String(150),
        existing_nullable=True,
    )
    op.alter_column(
        'content_requests',
        'caption_stories',
        type_=sa.Text(),
        existing_type=sa.String(100),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'content_requests',
        'caption_stories',
        type_=sa.String(100),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'content_requests',
        'caption_short',
        type_=sa.String(150),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
