"""add scheduled_for and scheduled status to content_requests (Epic 19)

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE não pode rodar dentro de uma transação
    # explícita junto de outros comandos DDL no mesmo statement do Alembic
    # em algumas versões do Postgres — mantido isolado, seguindo o padrão
    # já usado em e2f3a4b5c6d7 (add rejected to content_status).
    op.execute("ALTER TYPE content_status ADD VALUE IF NOT EXISTS 'scheduled'")

    op.add_column('content_requests', sa.Column(
        'scheduled_for',
        sa.DateTime(timezone=True),
        nullable=True,
        comment='Horário marcado para publicação automática (status=scheduled)',
    ))

    # Índice composto para o Celery Beat (Story 19.2) não fazer full scan
    # a cada tick de 1 minuto.
    op.create_index(
        'ix_content_requests_status_scheduled_for',
        'content_requests',
        ['status', 'scheduled_for'],
    )


def downgrade() -> None:
    op.drop_index('ix_content_requests_status_scheduled_for', table_name='content_requests')
    op.drop_column('content_requests', 'scheduled_for')
    # PostgreSQL não suporta remover valores de enum sem recriar o tipo.
    # Downgrade do valor 'scheduled' requer intervenção manual se necessário.
