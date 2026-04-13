"""
Conexão com Redis (broker Celery + cache).
"""

from redis.asyncio import Redis, from_url
from app.config import get_settings

settings = get_settings()

_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def get_redis() -> Redis:
    return get_redis_client()
