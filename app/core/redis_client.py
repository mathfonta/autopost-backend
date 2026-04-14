"""
Cliente Redis assíncrono para uso direto (sessões, cache).
Celery usa sua própria conexão — este módulo é para a aplicação FastAPI.
"""

import redis.asyncio as aioredis

from app.config import get_settings

_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Retorna (e cria se necessário) o cliente Redis compartilhado."""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _pool
