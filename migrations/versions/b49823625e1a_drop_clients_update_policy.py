"""drop clients_update_own rls policy

Revision ID: b49823625e1a
Revises: c5d6e7f8a9b1
Create Date: 2026-05-05 00:00:00.000000

Remove a política clients_update_own que permitia que usuários autenticados
alterassem qualquer coluna do próprio registro (incluindo 'plan') diretamente
via Supabase PostgREST — sem passar pelo backend.

Todos os updates legítimos de clients ocorrem via service_role (backend FastAPI),
que bypassa RLS por design. Não há uso legítimo para UPDATE direto via SDK cliente.

Achado: HIGH-RLS-001 — security-report-2026-05-05.md / rls-review-2026-05-05.md
Story: SEC-02
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b49823625e1a'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove a política de UPDATE para usuários autenticados.
    # O service_role (backend) continua com acesso irrestrito — bypassa RLS.
    op.execute('DROP POLICY IF EXISTS "clients_update_own" ON clients')

    # Remove também a política de UPDATE em content_requests — mesmo racional:
    # todos os updates passam pelo service_role. Usuário não precisa de UPDATE direto.
    op.execute('DROP POLICY IF EXISTS "content_requests_update_own" ON content_requests')


def downgrade() -> None:
    op.execute("""
        CREATE POLICY "clients_update_own"
        ON clients
        FOR UPDATE
        USING (auth.uid() = id)
        WITH CHECK (auth.uid() = id)
    """)

    op.execute("""
        CREATE POLICY "content_requests_update_own"
        ON content_requests
        FOR UPDATE
        USING (client_id = auth.uid())
        WITH CHECK (client_id = auth.uid())
    """)
