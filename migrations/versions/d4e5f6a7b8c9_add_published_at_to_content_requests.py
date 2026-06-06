"""add published_at to content_requests

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'content_requests',
        sa.Column(
            'published_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Momento exato da publicação nas redes sociais (imutável após set)',
        )
    )

    # Backfill: posts já publicados usam updated_at como aproximação
    op.execute("""
        UPDATE content_requests
        SET published_at = updated_at
        WHERE status = 'published' AND published_at IS NULL
    """)


def downgrade() -> None:
    op.drop_column('content_requests', 'published_at')
