"""add scout_report and scout_status to clients

Revision ID: f9a0b1c2d3e4
Revises: e5f6a7b8c9d0
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f9a0b1c2d3e4'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column(
        'scout_report',
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        comment='Relatório bruto do Agente Scout (Epic 22) — auditoria/debug',
    ))
    op.add_column('clients', sa.Column(
        'scout_status',
        sa.String(20),
        nullable=False,
        server_default='pending',
        comment='Status da análise do Scout: pending | running | done | skipped | failed',
    ))


def downgrade() -> None:
    op.drop_column('clients', 'scout_status')
    op.drop_column('clients', 'scout_report')
