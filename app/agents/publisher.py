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

        # Aguarda container ficar FINISHED (Instagram processa a imagem)
        import asyncio as _asyncio
        for _ in range(12):
            await _asyncio.sleep(5)
            status_resp = await client.get(
                f"{GRAPH_BASE}/{creation_id}",
                params={"fields": "status_code", "access_token": access_token},
            )
            status_code = status_resp.json().get("status_code", "")
            logger.info(f"[publisher] container status={status_code}")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                raise RuntimeError(f"Container falhou no processamento: {status_resp.json()}")

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


# ─── Instagram Carrossel ─────────────────────────────────────────────────────

async def publish_carousel_to_instagram(
    instagram_business_id: str,
    access_token: str,
    image_urls: list[str],
    caption: str,
) -> dict:
    """
    Publica carrossel no Instagram Business (N items → carousel container → publish).

    Returns:
        dict com: post_id, permalink
    """
    import asyncio as _asyncio

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # Etapa 1 — cria containers de item
        item_ids = []
        for img_url in image_urls:
            resp = await client.post(
                f"{GRAPH_BASE}/{instagram_business_id}/media",
                data={
                    "image_url": img_url,
                    "is_carousel_item": "true",
                    "access_token": access_token,
                },
            )
            data = resp.json()
            _raise_if_error(data, "ig_create_carousel_item")
            item_ids.append(data["id"])
            logger.info(f"[publisher] carousel item criado id={data['id']}")

        # Aguarda todos os items ficarem FINISHED
        for item_id in item_ids:
            for _ in range(12):
                await _asyncio.sleep(5)
                status_resp = await client.get(
                    f"{GRAPH_BASE}/{item_id}",
                    params={"fields": "status_code", "access_token": access_token},
                )
                sc = status_resp.json().get("status_code", "")
                logger.info(f"[publisher] carousel item={item_id} status={sc}")
                if sc == "FINISHED":
                    break
                if sc == "ERROR":
                    raise RuntimeError(f"Carousel item {item_id} falhou no processamento")

        # Etapa 2 — cria container carousel
        resp = await client.post(
            f"{GRAPH_BASE}/{instagram_business_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(item_ids),
                "caption": caption,
                "access_token": access_token,
            },
        )
        data = resp.json()
        _raise_if_error(data, "ig_create_carousel_container")
        carousel_id = data["id"]
        logger.info(f"[publisher] carousel container criado id={carousel_id}")

        # Aguarda carousel ficar FINISHED
        for _ in range(12):
            await _asyncio.sleep(5)
            status_resp = await client.get(
                f"{GRAPH_BASE}/{carousel_id}",
                params={"fields": "status_code", "access_token": access_token},
            )
            sc = status_resp.json().get("status_code", "")
            logger.info(f"[publisher] carousel container status={sc}")
            if sc == "FINISHED":
                break
            if sc == "ERROR":
                raise RuntimeError(f"Carousel container falhou: {status_resp.json()}")

        # Etapa 3 — publica
        resp = await client.post(
            f"{GRAPH_BASE}/{instagram_business_id}/media_publish",
            data={
                "creation_id": carousel_id,
                "access_token": access_token,
            },
        )
        data = resp.json()
        _raise_if_error(data, "ig_publish_carousel")
        post_id = data["id"]

        # Busca permalink
        resp = await client.get(
            f"{GRAPH_BASE}/{post_id}",
            params={"fields": "permalink", "access_token": access_token},
        )
        post_data = resp.json()
        permalink = post_data.get("permalink", "")

    logger.info(f"[publisher] carrossel publicado post_id={post_id}")
    return {"post_id": post_id, "permalink": permalink}


# ─── Instagram Reels ─────────────────────────────────────────────────────────

async def publish_reel_to_instagram(
    instagram_business_id: str,
    access_token: str,
    video_url: str,
    caption: str,
) -> dict:
    """
    Publica Reel no Instagram Business (media_type=REELS, async upload).

    O processamento de vídeo na Meta pode levar até 5 minutos.
    Faz polling de até 30 × 10s antes de considerar falha.

    Returns:
        dict com: post_id, permalink
    """
    import asyncio as _asyncio

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Etapa 1 — cria container de Reel
        resp = await client.post(
            f"{GRAPH_BASE}/{instagram_business_id}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true",
                "access_token": access_token,
            },
        )
        data = resp.json()
        _raise_if_error(data, "ig_create_reel_container")
        creation_id = data["id"]
        logger.info(f"[publisher] reel container criado creation_id={creation_id}")

        # Etapa 2 — aguarda processamento (vídeo é mais lento que imagem)
        for attempt in range(30):
            await _asyncio.sleep(10)
            status_resp = await client.get(
                f"{GRAPH_BASE}/{creation_id}",
                params={"fields": "status_code,status", "access_token": access_token},
            )
            status_data = status_resp.json()
            status_code = status_data.get("status_code", "")
            logger.info(f"[publisher] reel status={status_code} attempt={attempt + 1}/30")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                raise RuntimeError(f"Reel falhou no processamento: {status_data.get('status', 'erro desconhecido')}")
        else:
            raise RuntimeError("Timeout: vídeo não processado pela Meta em 5 minutos")

        # Etapa 3 — publica
        resp = await client.post(
            f"{GRAPH_BASE}/{instagram_business_id}/media_publish",
            data={
                "creation_id": creation_id,
                "access_token": access_token,
            },
        )
        data = resp.json()
        _raise_if_error(data, "ig_publish_reel")
        post_id = data["id"]

        # Busca permalink
        resp = await client.get(
            f"{GRAPH_BASE}/{post_id}",
            params={"fields": "permalink", "access_token": access_token},
        )
        permalink = resp.json().get("permalink", "")

    logger.info(f"[publisher] Reel publicado post_id={post_id}")
    return {"post_id": post_id, "permalink": permalink}


# ─── Instagram Story ──────────────────────────────────────────────────────────

async def publish_story_to_instagram(
    instagram_business_id: str,
    access_token: str,
    media_url: str,
    is_video: bool = False,
) -> dict:
    """
    Publica Story no Instagram Business.

    Stories não aceitam caption — a legenda é ignorada pela Meta API.
    Para vídeo: media_type=VIDEO; para imagem: media_type=IMAGE.

    Returns:
        dict com: post_id (permalink não disponível para Stories)
    """
    import asyncio as _asyncio

    media_type = "VIDEO" if is_video else "IMAGE"
    poll_retries = 30 if is_video else 12
    poll_interval = 10 if is_video else 5

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Etapa 1 — cria container de Story
        payload: dict = {
            "media_type": media_type,
            "access_token": access_token,
        }
        if is_video:
            payload["video_url"] = media_url
        else:
            payload["image_url"] = media_url

        resp = await client.post(
            f"{GRAPH_BASE}/{instagram_business_id}/media",
            data=payload,
        )
        data = resp.json()
        _raise_if_error(data, "ig_create_story_container")
        creation_id = data["id"]
        logger.info(f"[publisher] story container criado creation_id={creation_id} is_video={is_video}")

        # Etapa 2 — aguarda processamento
        for attempt in range(poll_retries):
            await _asyncio.sleep(poll_interval)
            status_resp = await client.get(
                f"{GRAPH_BASE}/{creation_id}",
                params={"fields": "status_code,status", "access_token": access_token},
            )
            status_data = status_resp.json()
            status_code = status_data.get("status_code", "")
            logger.info(f"[publisher] story status={status_code} attempt={attempt + 1}/{poll_retries}")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                raise RuntimeError(f"Story falhou no processamento: {status_data.get('status', 'erro desconhecido')}")
        else:
            raise RuntimeError("Timeout: Story não processada pela Meta")

        # Etapa 3 — publica
        resp = await client.post(
            f"{GRAPH_BASE}/{instagram_business_id}/media_publish",
            data={
                "creation_id": creation_id,
                "access_token": access_token,
            },
        )
        data = resp.json()
        _raise_if_error(data, "ig_publish_story")
        post_id = data["id"]

    logger.info(f"[publisher] Story publicada post_id={post_id}")
    return {"post_id": post_id, "permalink": ""}


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
