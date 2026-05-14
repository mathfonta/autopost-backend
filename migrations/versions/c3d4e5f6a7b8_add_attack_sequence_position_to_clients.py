"""add attack_sequence_position to clients

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column(
        'attack_sequence_position',
        sa.Integer(),
        nullable=False,
        server_default='0',
        comment='Posição na sequência de ataque editorial (Story 14.2) — 0 a 10',
    ))

    # Clientes que já publicaram >= 10 posts saem da sequência de ataque
    op.execute("""
        UPDATE clients
        SET attack_sequence_position = 10
        WHERE id IN (
            SELECT client_id
            FROM content_requests
            WHERE status = 'published'
            GROUP BY client_id
            HAVING COUNT(*) >= 10
        )
    """)


def downgrade() -> None:
    op.drop_column('clients', 'attack_sequence_position')
