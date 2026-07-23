"""
Tool de leitura de mídia e conta do Instagram — reusa o token/escopo já
concedido na conexão OAuth (instagram_business_basic) para o Agente Scout
(Epic 22).

Uso:
    from app.tools.instagram_media import fetch_recent_media, fetch_account_info
    media = await fetch_recent_media(ig_id, access_token, limit=12)
    account = await fetch_account_info(ig_id, access_token)

Escopo confirmado (Story 22.1, pre-flight 2026-07-22 — via documentação oficial
Meta, Instagram Platform / Instagram Login): todos os campos usados aqui estão
disponíveis sob instagram_business_basic — sem necessidade de escopo adicional
nem novo App Review.

Fallback: qualquer falha (rede, token inválido/expirado, conta vazia/privada,
resposta malformada) loga WARNING e retorna [] / None — nunca levanta exceção.
O Agente Scout (Story 22.2) depende dessa degradação graciosa.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

INSTAGRAM_GRAPH_BASE = "https://graph.instagram.com"
TIMEOUT = 30.0

MEDIA_FIELDS = (
    "id,caption,media_type,media_url,thumbnail_url,"
    "permalink,timestamp,like_count,comments_count"
)
ACCOUNT_FIELDS = "username,biography,followers_count,media_count,profile_picture_url"


async def _instagram_get(endpoint: str, params: dict) -> dict:
    """GET na Instagram Graph API com tratamento do erro #190 (token expirado/inválido)."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(f"{INSTAGRAM_GRAPH_BASE}/{endpoint}", params=params)
            body = resp.json()
        except httpx.RequestError as exc:
            return {"error": str(exc), "code": 500}
        except ValueError as exc:
            return {"error": f"Resposta inválida da API: {exc}", "code": 502}

    if not isinstance(body, dict):
        return {"error": "Formato de resposta inesperado da Instagram Graph API", "code": 502}

    if "error" in body:
        error = body["error"]
        code = error.get("code") if isinstance(error, dict) else None
        if code == 190:
            return {"error": "Token Instagram expirou ou foi revogado.", "code": 190}
        message = (
            error.get("message", "Erro desconhecido na Instagram Graph API")
            if isinstance(error, dict)
            else str(error)
        )
        return {"error": message, "code": code}

    return {"data": body, "status": 200}


async def fetch_recent_media(ig_id: str, access_token: str, limit: int = 12) -> list[dict]:
    """
    Busca os posts mais recentes do cliente conectado.

    Args:
        ig_id: Instagram Business Account ID do cliente.
        access_token: Long-Lived Token Instagram do cliente.
        limit: Quantidade máxima de posts (padrão 12 — contém custo/latência
               da análise a jusante no Scout).

    Returns:
        Lista de dicts com id, caption, media_type, media_url, thumbnail_url,
        permalink, timestamp, like_count, comments_count.
        Lista vazia em qualquer falha, conta sem posts, ou resposta malformada
        — nunca levanta exceção.
    """
    if not ig_id or not access_token:
        logger.warning("[instagram_media] ig_id ou access_token ausente — retornando []")
        return []

    result = await _instagram_get(
        f"{ig_id}/media",
        {"fields": MEDIA_FIELDS, "limit": limit, "access_token": access_token},
    )

    if "error" in result:
        logger.warning(
            f"[instagram_media] fetch_recent_media falhou ig_id={ig_id}: {result['error']}"
        )
        return []

    media = result["data"].get("data", [])
    if not isinstance(media, list):
        logger.warning(
            f"[instagram_media] resposta malformada (campo 'data' não é lista) ig_id={ig_id}"
        )
        return []

    logger.info(f"[instagram_media] ig_id={ig_id} — {len(media)} posts recuperados")
    return media


async def fetch_account_info(ig_id: str, access_token: str) -> dict | None:
    """
    Busca dados de conta (bio, username, seguidores) do cliente conectado.

    Resolve a Decisão #1 do Epic 22 — a bio do perfil é acessível sob o
    escopo instagram_business_basic já concedido no OAuth.

    Args:
        ig_id: Instagram Business Account ID do cliente.
        access_token: Long-Lived Token Instagram do cliente.

    Returns:
        dict com username, biography, followers_count, media_count,
        profile_picture_url, ou None em qualquer falha.
    """
    if not ig_id or not access_token:
        logger.warning("[instagram_media] ig_id ou access_token ausente — retornando None")
        return None

    result = await _instagram_get(
        ig_id,
        {"fields": ACCOUNT_FIELDS, "access_token": access_token},
    )

    if "error" in result:
        logger.warning(
            f"[instagram_media] fetch_account_info falhou ig_id={ig_id}: {result['error']}"
        )
        return None

    logger.info(f"[instagram_media] ig_id={ig_id} — dados de conta recuperados")
    return result["data"]
