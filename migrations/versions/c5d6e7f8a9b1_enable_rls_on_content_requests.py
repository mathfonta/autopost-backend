"""enable rls on content_requests

Revision ID: c5d6e7f8a9b1
Revises: a3b4c5d6e7f8, b2c3d4e5f6a1
Create Date: 2026-05-03 00:00:00.000000

Merge das duas branches divergentes + habilita RLS em content_requests.

RLS protege acesso direto ao banco via SDK cliente (anon/user key) ou PostgREST.
O service_role key usado pelo backend bypassa RLS automaticamente — sem impacto na API.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b1'
down_revision: Union[str, Sequence[str], None] = ('a3b4c5d6e7f8', 'b2c3d4e5f6a1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Habilita RLS na tabela content_requests e cria políticas de acesso.

    - Usuários autenticados só acessam/modificam seus próprios registros (auth.uid() = client_id).
    - O service_role key do backend bypassa RLS automaticamente — sem impacto na API existente.
    - As políticas protegem contra: acesso direto via SDK cliente, futura exposição via PostgREST.
    """
    op.execute("ALTER TABLE content_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE content_requests FORCE ROW LEVEL SECURITY")

    # SELECT: cada cliente vê apenas seus próprios content_requests
    op.execute("""
        CREATE POLICY "content_requests_select_own"
        ON content_requests
        FOR SELECT
        USING (client_id = auth.uid())
    """)

    # INSERT: cliente só insere com seu próprio client_id
    op.execute("""
        CREATE POLICY "content_requests_insert_own"
        ON content_requests
        FOR INSERT
        WITH CHECK (client_id = auth.uid())
    """)

    # UPDATE: cliente só atualiza seus próprios registros
    op.execute("""
        CREATE POLICY "content_requests_update_own"
        ON content_requests
        FOR UPDATE
        USING (client_id = auth.uid())
        WITH CHECK (client_id = auth.uid())
    """)

    # DELETE: cliente só exclui seus próprios registros
    op.execute("""
        CREATE POLICY "content_requests_delete_own"
        ON content_requests
        FOR DELETE
        USING (client_id = auth.uid())
    """)


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS "content_requests_delete_own" ON content_requests')
    op.execute('DROP POLICY IF EXISTS "content_requests_update_own" ON content_requests')
    op.execute('DROP POLICY IF EXISTS "content_requests_insert_own" ON content_requests')
    op.execute('DROP POLICY IF EXISTS "content_requests_select_own" ON content_requests')
    op.execute("ALTER TABLE content_requests DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE content_requests NO FORCE ROW LEVEL SECURITY")
