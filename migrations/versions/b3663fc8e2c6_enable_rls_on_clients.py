"""enable rls on clients

Revision ID: b3663fc8e2c6
Revises: 370b6a5365d0
Create Date: 2026-04-13 20:57:53.462959

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3663fc8e2c6'
down_revision: Union[str, Sequence[str], None] = '370b6a5365d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Habilita RLS na tabela clients e cria políticas de acesso.

    - Usuários autenticados só podem ler/atualizar o próprio registro (auth.uid() = id).
    - O service_role key do backend bypassa RLS automaticamente — sem impacto na API.
    - A política de SELECT/UPDATE protege acesso direto via SDK cliente (anon/user key).
    """
    op.execute("ALTER TABLE clients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clients FORCE ROW LEVEL SECURITY")

    # SELECT: cada usuário vê apenas o próprio client
    op.execute("""
        CREATE POLICY "clients_select_own"
        ON clients
        FOR SELECT
        USING (auth.uid() = id)
    """)

    # UPDATE: cada usuário atualiza apenas o próprio client
    op.execute("""
        CREATE POLICY "clients_update_own"
        ON clients
        FOR UPDATE
        USING (auth.uid() = id)
        WITH CHECK (auth.uid() = id)
    """)

    # INSERT e DELETE são controlados exclusivamente pelo service_role (backend)
    # Não criamos políticas para INSERT/DELETE — significa: bloqueado para user/anon key


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS "clients_update_own" ON clients')
    op.execute('DROP POLICY IF EXISTS "clients_select_own" ON clients')
    op.execute("ALTER TABLE clients DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clients NO FORCE ROW LEVEL SECURITY")
