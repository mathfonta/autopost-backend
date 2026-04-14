"""add meta fields to clients and publish_result to content_requests

Revision ID: c4f1a8d92e3b
Revises: 2287a06a1f54
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c4f1a8d92e3b'
down_revision: Union[str, Sequence[str], None] = '2287a06a1f54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── clients: campos Meta / Instagram ─────────────────────────
    op.add_column('clients', sa.Column(
        'meta_access_token', sa.String(500), nullable=True,
        comment='Long-Lived Token Meta Graph API'
    ))
    op.add_column('clients', sa.Column(
        'instagram_business_id', sa.String(100), nullable=True,
        comment='Instagram Business Account ID'
    ))
    op.add_column('clients', sa.Column(
        'facebook_page_id', sa.String(100), nullable=True,
        comment='Facebook Page ID'
    ))

    # ── content_requests: resultado da publicação ─────────────────
    op.add_column('content_requests', sa.Column(
        'publish_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
        comment='Output do Agente Publicador (IDs, permalink, métricas)'
    ))


def downgrade() -> None:
    op.drop_column('content_requests', 'publish_result')
    op.drop_column('clients', 'facebook_page_id')
    op.drop_column('clients', 'instagram_business_id')
    op.drop_column('clients', 'meta_access_token')
