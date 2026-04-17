"""
Endpoints OAuth Meta — conectar Instagram/Facebook.

GET /meta/connect    → retorna {auth_url} para iniciar o fluxo OAuth
GET /meta/callback   → troca code por Long-Lived Token e salva IDs no Client
GET /meta/status     → retorna status da conexão e dados da conta
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import get_current_client
from app.core.database import get_db
from app.core.meta_oauth import (
    build_auth_url,
    create_state_token,
    decode_state_token,
    exchange_code_for_short_token,
    exchange_for_long_lived_token,
    get_instagram_business_info,
)
from app.models.client import Client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meta", tags=["meta"])


# ─── GET /meta/connect ───────────────────────────────────────────

@router.get("/connect")
async def meta_connect(
    current_client: Client = Depends(get_current_client),
):
    """
    Inicia o fluxo OAuth Meta.
    Retorna a URL de autorização para o cliente redirecionar o usuário.
    """
    settings = get_settings()
    state = create_state_token(str(current_client.id), settings.JWT_SECRET)
    auth_url = build_auth_url(
        app_id=settings.META_APP_ID,
        redirect_uri=settings.META_REDIRECT_URI,
        state=state,
    )
    return {"auth_url": auth_url}


# ─── GET /meta/callback ──────────────────────────────────────────

@router.get("/callback")
async def meta_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Callback do Meta OAuth.
    Valida o state, troca o code pelo Long-Lived Token,
    busca os IDs do Instagram Business e salva tudo no Client.
    """
    settings = get_settings()

    # 1. Validar state JWT e recuperar client_id
    client_id_str = decode_state_token(state, settings.JWT_SECRET)

    # 2. Buscar Client no banco
    try:
        client_uuid = uuid.UUID(client_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="client_id inválido no state.")

    result = await db.execute(select(Client).where(Client.id == client_uuid))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=400, detail="Cliente não encontrado.")

    # 3. Short-Lived Token
    short_token = await exchange_code_for_short_token(
        code=code,
        app_id=settings.META_APP_ID,
        app_secret=settings.META_APP_SECRET,
        redirect_uri=settings.META_REDIRECT_URI,
    )

    # 4. Long-Lived Token
    long_token, expires_at = await exchange_for_long_lived_token(
        short_token=short_token,
        app_id=settings.META_APP_ID,
        app_secret=settings.META_APP_SECRET,
    )

    # 5. Buscar IDs do Instagram Business
    page_id, page_name, ig_id, ig_username = await get_instagram_business_info(long_token)

    # 6. Persistir no banco
    client.meta_access_token = long_token
    client.meta_token_expires_at = expires_at
    client.facebook_page_id = page_id
    client.facebook_page_name = page_name
    client.instagram_business_id = ig_id
    client.instagram_username = ig_username
    await db.commit()

    logger.info(f"[meta] cliente {client.id} conectou IG @{ig_username} / página '{page_name}'")
    return {
        "connected": True,
        "instagram_username": ig_username,
        "facebook_page_name": page_name,
    }


# ─── GET /meta/status ────────────────────────────────────────────

@router.get("/status")
async def meta_status(
    current_client: Client = Depends(get_current_client),
):
    """Retorna o status de conexão com Meta/Instagram do cliente autenticado."""
    if not current_client.meta_access_token:
        return {
            "connected": False,
            "instagram_username": None,
            "facebook_page_name": None,
            "token_expires_at": None,
        }

    expires_at = current_client.meta_token_expires_at
    return {
        "connected": True,
        "instagram_username": current_client.instagram_username,
        "facebook_page_name": current_client.facebook_page_name,
        "token_expires_at": expires_at.isoformat() if expires_at else None,
    }
