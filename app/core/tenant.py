"""
Helpers de multi-tenancy.
Garante que um client só acessa recursos que pertencem a ele.
"""

import uuid
from fastapi import HTTPException

from app.models.client import Client


def require_ownership(resource_client_id: uuid.UUID, current_client: Client) -> None:
    """
    Levanta 403 se o resource não pertence ao client autenticado.

    Uso nos endpoints:
        require_ownership(post.client_id, current_client)
    """
    if resource_client_id != current_client.id:
        raise HTTPException(
            status_code=403,
            detail="Acesso negado: recurso pertence a outro cliente",
        )


def tenant_filter(query, model, current_client: Client):
    """
    Aplica filtro WHERE client_id = ? em uma query SQLAlchemy.

    Uso:
        q = tenant_filter(select(Post), Post, current_client)
        result = await db.execute(q)
    """
    return query.where(model.client_id == current_client.id)
