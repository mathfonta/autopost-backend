"""add suggested_time to weekly_context (Epic 19, Story 19.3)

Revision ID: 18ec2311ad3b
Revises: c5581ee0ad14
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '18ec2311ad3b'
down_revision: Union[str, Sequence[str], None] = 'c5581ee0ad14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('weekly_context', sa.Column(
        'suggested_time',
        sa.String(5),
        nullable=True,
        comment='Melhor horário sugerido (HH:MM) extraído de busca Exa sobre boas práticas do nicho',
    ))


def downgrade() -> None:
    op.drop_column('weekly_context', 'suggested_time')
