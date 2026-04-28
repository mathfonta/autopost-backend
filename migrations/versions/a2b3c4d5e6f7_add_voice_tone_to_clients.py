"""add voice_tone to clients

Revision ID: a2b3c4d5e6f7
Revises: f3a4b5c6d7e8
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'clients',
        sa.Column(
            'voice_tone',
            sa.String(20),
            nullable=True,
            server_default='casual',
            comment='Tom de voz do copywriter: formal | casual | technical',
        )
    )
    op.create_check_constraint(
        'ck_clients_voice_tone',
        'clients',
        "voice_tone IN ('formal', 'casual', 'technical')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_clients_voice_tone', 'clients', type_='check')
    op.drop_column('clients', 'voice_tone')
