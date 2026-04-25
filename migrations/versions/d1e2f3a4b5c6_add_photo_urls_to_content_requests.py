"""add photo_urls and photo_keys to content_requests

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a1b2
Create Date: 2026-04-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'c3d4e5f6a1b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'content_requests',
        sa.Column('photo_urls', postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        'content_requests',
        sa.Column('photo_keys', postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('content_requests', 'photo_keys')
    op.drop_column('content_requests', 'photo_urls')
