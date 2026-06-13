"""
Endpoints OAuth Meta — conectar Instagram/Facebook.

GET /meta/connect    → retorna {auth_url} para iniciar o fluxo OAuth
GET /meta/callback   → troca code por Long-Lived Token e salva IDs no Client
GET /meta/status     → retorna status da conexão e dados da conta
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import get_current_client
from app.core.database import get_db
from datetime import datetime, timezone, timedelta

from app.core.meta_oauth import (
    build_auth_url,
    create_state_token,
    decode_state_token,
    exchange_code_for_short_token,
    exchange_for_long_lived_token,
    refresh_long_lived_token,
    get_instagram_user_info,
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
        app_id=settings.INSTAGRAM_APP_ID,
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
        app_id=settings.INSTAGRAM_APP_ID,
        app_secret=settings.INSTAGRAM_APP_SECRET,
        redirect_uri=settings.META_REDIRECT_URI,
    )

    # 4. Long-Lived Token
    long_token, expires_at = await exchange_for_long_lived_token(
        short_token=short_token,
        app_id=settings.INSTAGRAM_APP_ID,
        app_secret=settings.INSTAGRAM_APP_SECRET,
    )

    # 5. Buscar ID e username da conta Instagram
    ig_id, ig_username = await get_instagram_user_info(long_token)

    # 6. Persistir no banco
    client.meta_access_token = long_token
    client.meta_token_expires_at = expires_at
    client.instagram_business_id = ig_id
    client.instagram_username = ig_username
    await db.commit()

    logger.info(f"[meta] cliente {client.id} conectou Instagram @{ig_username}")
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(
        url=f"{frontend_url}/onboarding?connected=true&username={ig_username}",
        status_code=302,
    )


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
    now = datetime.now(timezone.utc)
    days_until_expiry = None
    if expires_at:
        delta = expires_at - now
        days_until_expiry = max(0, delta.days)

    return {
        "connected": True,
        "instagram_username": current_client.instagram_username,
        "facebook_page_name": current_client.facebook_page_name,
        "token_expires_at": expires_at.isoformat() if expires_at else None,
        "days_until_expiry": days_until_expiry,
        "token_expiring_soon": days_until_expiry is not None and days_until_expiry <= 10,
    }


# ─── POST /meta/refresh ──────────────────────────────────────────

@router.post("/refresh")
async def meta_refresh(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Renova manualmente o Long-Lived Token Meta do cliente autenticado.
    Útil quando o token está prestes a expirar.
    """
    if not current_client.meta_access_token:
        raise HTTPException(status_code=400, detail="Nenhuma conta Meta conectada.")

    try:
        new_token, new_expires_at = await refresh_long_lived_token(
            long_token=current_client.meta_access_token,
        )
    except Exception as exc:
        logger.error(f"[meta/refresh] falha na renovação client_id={current_client.id}: {exc}")
        raise HTTPException(
            status_code=502,
            detail="Não foi possível renovar o token. Reconecte sua conta Meta.",
        )

    current_client.meta_access_token = new_token
    current_client.meta_token_expires_at = new_expires_at
    await db.commit()

    logger.info(f"[meta/refresh] token renovado client_id={current_client.id} expires={new_expires_at.date()}")
    return {
        "renewed": True,
        "token_expires_at": new_expires_at.isoformat(),
        "days_until_expiry": 60,
    }


# ─── DELETE /meta/disconnect ─────────────────────────────────────

@router.delete("/disconnect")
async def meta_disconnect(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a conexão Meta/Instagram do cliente autenticado.
    Limpa token, datas de expiração e IDs da conta Instagram.
    """
    current_client.meta_access_token = None
    current_client.meta_token_expires_at = None
    current_client.instagram_business_id = None
    current_client.instagram_username = None
    current_client.facebook_page_name = None
    await db.commit()

    logger.info(f"[meta/disconnect] cliente {current_client.id} desconectou Instagram")
    return {"disconnected": True}


# ─── POST /meta/data-deletion ────────────────────────────────────
# Obrigatório pelo Instagram Login (Meta App Review).
# Chamado quando usuário remove o app via instagram.com → Configurações → Apps e sites.

@router.post("/data-deletion")
async def meta_data_deletion(
    signed_request: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Callback de deleção de dados exigido pela Meta.
    Recebe signed_request, valida assinatura, remove tokens do cliente.
    Retorna URL de confirmação e código de rastreamento.
    """
    settings = get_settings()

    # Decodifica e valida o signed_request
    try:
        parts = signed_request.split(".", 1)
        if len(parts) != 2:
            raise ValueError("formato inválido")

        encoded_sig, payload_b64 = parts

        # Normaliza base64url → base64 padrão
        def _b64_decode(s: str) -> bytes:
            s += "=" * (-len(s) % 4)
            return base64.urlsafe_b64decode(s)

        sig = _b64_decode(encoded_sig)
        payload_bytes = _b64_decode(payload_b64)

        # Verifica assinatura HMAC-SHA256
        expected = hmac.new(
            settings.INSTAGRAM_APP_SECRET.encode(),
            payload_bytes,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("assinatura inválida")

        payload = json.loads(payload_bytes)
        ig_user_id = str(payload.get("user_id", ""))
    except Exception as exc:
        logger.warning(f"[meta/data-deletion] signed_request inválido: {exc}")
        raise HTTPException(status_code=400, detail="signed_request inválido.")

    # Remove token da conta Instagram associada ao ig_user_id
    result = await db.execute(
        select(Client).where(Client.instagram_business_id == ig_user_id)
    )
    client = result.scalar_one_or_none()
    if client:
        client.meta_access_token = None
        client.meta_token_expires_at = None
        await db.commit()
        logger.info(f"[meta/data-deletion] token removido ig_user_id={ig_user_id} client_id={client.id}")
    else:
        logger.info(f"[meta/data-deletion] ig_user_id={ig_user_id} não encontrado — nenhuma ação necessária")

    # Retorna URL de status e código de confirmação (exigido pela Meta)
    confirmation_code = hashlib.sha256(f"{ig_user_id}-deleted".encode()).hexdigest()[:16]
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    return {
        "url": f"{frontend_url}/privacy#data-deletion",
        "confirmation_code": confirmation_code,
    }
