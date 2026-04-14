"""
Agente Publicador — publica posts aprovados no Instagram Business e Facebook
via Meta Graph API v21+.

#OBJETIVO
Publicar a imagem processada + legenda no(s) canal(is) do cliente e registrar
os IDs de publicação para rastreamento de métricas.

#DIRETRIZES
- Processo Instagram: 2 etapas (create container → publish)
- Facebook: 1 etapa (POST /photos)
- Token expirado → falha com mensagem orientando renovação
- Falha no Facebook não cancela publicação do Instagram

#CONTEXTO
- Imagem já processada (1080×1080, ≤8MB) disponível em URL pública do R2
- Legenda, hashtags e CTA vêm do copy_result
- Credenciais Meta por cliente (meta_access_token, instagram_business_id, facebook_page_id)

#RESTRIÇÕES
- Nunca expor access_token em logs
- Timeout de 30s por chamada de API
- Métricas coletadas 24h após publicação (task separada)
"""

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
TIMEOUT = 30.0


# ─── Erros ──────────────────────────────────────────────────────────────────

class MetaAPIError(Exception):
    """Erro retornado pela Meta Graph API."""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code
        # Códigos 190 e 102 indicam token inválido/expirado
        self.is_token_expired = code in (102, 190)


def _raise_if_error(data: dict, operation: str) -> None:
    if "error" in data:
        err = data["error"]
        raise MetaAPIError(
            f"[{operation}] {err.get('message', 'Erro desconhecido')}",
            code=err.get("code", 0),
        )


# ─── Instagram ───────────────────────────────────────────────────────────────

async def publish_to_instagram(
    instagram_business_id: str,
    access_token: str,
    image_url: str,
    caption: str,
) -> dict:
    """
    Publica imagem no Instagram Business (processo em 2 etapas).

    Returns:
        dict com: post_id, permalink
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Etapa 1 — cria container de mídia
        resp = await client.post(
            f"{GRAPH_BASE}/{instagram_business_id}/media",
            data={
                "image_url": image_url,
                "caption": caption,
                "access_token": access_token,
            },
        )
        data = resp.json()
        _raise_if_error(data, "ig_create_container")
        creation_id = data["id"]
        logger.info(f"[publisher] container criado creation_id={creation_id}")

        # Etapa 2 — publica
        resp = await client.post(
            f"{GRAPH_BASE}/{instagram_business_id}/media_publish",
            data={
                "creation_id": creation_id,
                "access_token": access_token,
            },
        )
        data = resp.json()
        _raise_if_error(data, "ig_media_publish")
        post_id = data["id"]

        # Busca permalink
        resp = await client.get(
            f"{GRAPH_BASE}/{post_id}",
            params={"fields": "permalink", "access_token": access_token},
        )
        post_data = resp.json()
        permalink = post_data.get("permalink", "")

    logger.info(f"[publisher] Instagram publicado post_id={post_id}")
    return {"post_id": post_id, "permalink": permalink}


# ─── Facebook ────────────────────────────────────────────────────────────────

async def publish_to_facebook(
    facebook_page_id: str,
    access_token: str,
    image_url: str,
    caption: str,
) -> dict:
    """
    Publica imagem na Página do Facebook.

    Returns:
        dict com: post_id
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(
            f"{GRAPH_BASE}/{facebook_page_id}/photos",
            data={
                "url": image_url,
                "message": caption,
                "access_token": access_token,
            },
        )
        data = resp.json()
        _raise_if_error(data, "fb_publish_photo")
        post_id = data.get("post_id") or data.get("id", "")

    logger.info(f"[publisher] Facebook publicado post_id={post_id}")
    return {"post_id": post_id}


# ─── Métricas ────────────────────────────────────────────────────────────────

async def collect_post_metrics(
    instagram_post_id: str,
    access_token: str,
) -> dict:
    """
    Coleta métricas do post Instagram 24h após publicação.

    Returns:
        dict com: impressions, reach, likes, comments, collected_at
    """
    metrics = {"impressions": 0, "reach": 0, "likes": 0, "comments": 0}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Impressões e alcance
        resp = await client.get(
            f"{GRAPH_BASE}/{instagram_post_id}/insights",
            params={
                "metric": "impressions,reach",
                "access_token": access_token,
            },
        )
        data = resp.json()
        if "data" in data:
            for item in data["data"]:
                name = item.get("name")
                values = item.get("values", [])
                if values and name in metrics:
                    metrics[name] = values[-1].get("value", 0)

        # Curtidas e comentários
        resp = await client.get(
            f"{GRAPH_BASE}/{instagram_post_id}",
            params={
                "fields": "like_count,comments_count",
                "access_token": access_token,
            },
        )
        post_data = resp.json()
        metrics["likes"] = post_data.get("like_count", 0)
        metrics["comments"] = post_data.get("comments_count", 0)

    metrics["collected_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(f"[publisher] métricas coletadas post_id={instagram_post_id} {metrics}")
    return metrics


# ─── Helper: monta legenda completa ─────────────────────────────────────────

def build_full_caption(copy_result: dict) -> str:
    """Junta caption + CTA + hashtags no formato Instagram."""
    caption = copy_result.get("caption", "")
    cta = copy_result.get("cta", "")
    hashtags = " ".join(f"#{h}" for h in copy_result.get("hashtags", []))

    parts = [p for p in [caption, cta, hashtags] if p]
    return "\n\n".join(parts)
