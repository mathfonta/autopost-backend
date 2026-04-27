"""add rejected to content_status enum

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-26

"""
from alembic import op

revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE content_status ADD VALUE IF NOT EXISTS 'rejected'")


def downgrade() -> None:
    # PostgreSQL não suporta remover valores de enum sem recriar o tipo.
    # Downgrade requer intervenção manual se necessário.
    pass
