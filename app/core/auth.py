"""
Dependência de autenticação JWT.
Verifica o token via Supabase Auth e retorna o Client do banco.
"""

import uuid
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.supabase import supabase_get_user
from app.models.client import Client

security = HTTPBearer()


async def get_current_client(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: AsyncSession = Depends(get_db),
) -> Client:
    """
    Dependência para rotas protegidas.
    Verifica JWT via Supabase e retorna o Client correspondente.
    """
    token = credentials.credentials

    # 1. Verifica token no Supabase Auth
    try:
        response = await supabase_get_user(token)
        user_id = response.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    # 2. Busca Client no banco
    result = await db.execute(
        select(Client).where(Client.id == uuid.UUID(str(user_id)))
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    if not client.is_active:
        raise HTTPException(status_code=403, detail="Conta desativada")

    return client
