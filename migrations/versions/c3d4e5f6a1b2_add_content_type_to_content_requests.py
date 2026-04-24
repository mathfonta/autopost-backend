"""add content_type to content_requests

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a1b2"
down_revision = "b2c3d4e5f6a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_requests",
        sa.Column("content_type", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_requests", "content_type")
