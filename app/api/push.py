"""
Endpoints de Web Push Notifications.
POST /push/subscribe — salva subscription do cliente no Redis
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.core.auth import get_current_client
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/push", tags=["push"])


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict[str, Any]
    expirationTime: Any = None


@router.post("/subscribe", status_code=204)
async def subscribe_push(
    subscription: PushSubscription,
    client=Depends(get_current_client),
):
    """Salva a subscription de push do cliente autenticado."""
    settings = get_settings()
    if not settings.VAPID_PRIVATE_KEY:
        raise HTTPException(status_code=503, detail="Push não configurado")

    redis = await get_redis()
    key = f"push_subscription:{client.id}"
    await redis.set(key, subscription.model_dump_json(), ex=60 * 60 * 24 * 30)  # 30 dias

    logger.info(f"[push] subscription salva client_id={client.id}")
    return None


async def send_push_notification(client_id: str, title: str, body: str, url: str) -> bool:
    """
    Envia notificação push para um cliente via pywebpush.
    Retorna True se enviado, False se sem subscription ou erro.
    """
    try:
        from pywebpush import webpush, WebPushException
        import redis.asyncio as aioredis

        settings = get_settings()
        if not settings.VAPID_PRIVATE_KEY:
            return False

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = await r.get(f"push_subscription:{client_id}")
        await r.aclose()

        if not raw:
            return False

        sub = json.loads(raw)
        payload = json.dumps({"title": title, "body": body, "url": url})

        webpush(
            subscription_info=sub,
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_EMAIL},
        )
        return True

    except Exception as exc:
        logger.warning(f"[push] falha ao enviar push client_id={client_id}: {exc}")
        return False
