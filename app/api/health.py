"""
Endpoint de health check.
Verifica conexões com PostgreSQL e Redis.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from redis.asyncio import Redis

from app.config import get_settings
from app.core.database import get_db
from app.core.redis import get_redis

router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Verifica status de todos os serviços."""
    checks = {
        "api": "ok",
        "database": "unknown",
        "redis": "unknown",
    }

    # Verifica banco
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # Verifica Redis
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "version": settings.APP_VERSION,
        "env": settings.ENV,
        "services": checks,
    }
