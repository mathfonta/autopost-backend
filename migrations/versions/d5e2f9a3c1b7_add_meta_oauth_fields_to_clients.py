"""add meta oauth fields to clients (token_expires_at, instagram_username, facebook_page_name)

Revision ID: d5e2f9a3c1b7
Revises: c4f1a8d92e3b
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e2f9a3c1b7'
down_revision: Union[str, Sequence[str], None] = 'c4f1a8d92e3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clients', sa.Column(
        'meta_token_expires_at',
        sa.DateTime(timezone=True),
        nullable=True,
        comment='Expiração do Long-Lived Token Meta',
    ))
    op.add_column('clients', sa.Column(
        'instagram_username', sa.String(100), nullable=True,
        comment='Username público do Instagram',
    ))
    op.add_column('clients', sa.Column(
        'facebook_page_name', sa.String(255), nullable=True,
        comment='Nome da Página do Facebook',
    ))


def downgrade() -> None:
    op.drop_column('clients', 'facebook_page_name')
    op.drop_column('clients', 'instagram_username')
    op.drop_column('clients', 'meta_token_expires_at')
