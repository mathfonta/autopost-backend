"""
Endpoints de inteligência de mercado (Story 13.4) e analytics Instagram.

GET /insights/weekly      — último WeeklyContext para o segmento do client
GET /insights/streak      — streak de publicação do client
GET /insights/instagram   — métricas orgânicas de conta (30d), cache Redis 6h
"""

import json
import logging
import unicodedata
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.instagram_analytics import get_instagram_analytics_30d
from app.core.auth import get_current_client
from app.data.theme_library import THEME_LIBRARY
from app.core.database import get_db
from app.core.redis_client import get_redis
from app.models.client import Client
from app.models.content_request import ContentRequest, ContentStatus
from app.models.weekly_context import WeeklyContext
from app.schemas.weekly_context import WeeklyContextResponse, StreakResponse

ANALYTICS_CACHE_TTL = 6 * 3600  # 6 horas

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/weekly", response_model=WeeklyContextResponse)
async def get_weekly_insight(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna o último WeeklyContext para o segmento do client autenticado.

    Filtra por `segment` extraído do perfil do client (business_segment).
    Se não houver dados disponíveis, retorna 404.
    """
    segment = getattr(current_client, "business_segment", None) or "geral"

    # Busca o registro mais recente para o segmento
    stmt = (
        select(WeeklyContext)
        .where(WeeklyContext.segment == segment)
        .order_by(desc(WeeklyContext.week_of))
        .limit(1)
    )
    result = await db.execute(stmt)
    weekly = result.scalar_one_or_none()

    if weekly is None:
        # Fallback: tenta buscar da semana atual independente do segmento
        monday = _current_monday()
        stmt_any = (
            select(WeeklyContext)
            .order_by(desc(WeeklyContext.week_of))
            .limit(1)
        )
        result_any = await db.execute(stmt_any)
        weekly = result_any.scalar_one_or_none()

    if weekly is None:
        raise HTTPException(
            status_code=404,
            detail="Nenhuma inteligência de mercado disponível ainda. "
                   "Os dados são gerados toda segunda-feira às 07h.",
        )

    logger.info(
        f"[insights] weekly context entregue — segment={weekly.segment} "
        f"week_of={weekly.week_of} client={current_client.id}"
    )
    return weekly


@router.get("/streak", response_model=StreakResponse)
async def get_streak(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna streak de dias consecutivos e progresso semanal do client autenticado.
    Conta apenas posts com status = 'published'.
    """
    stmt = select(ContentRequest.updated_at).where(
        ContentRequest.client_id == current_client.id,
        ContentRequest.status == ContentStatus.published,
    )
    result = await db.execute(stmt)
    published_dates: set[date] = {row[0].date() for row in result.fetchall()}

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    week_days = [
        (monday + timedelta(days=i)) in published_dates
        for i in range(7)
    ]

    streak = 0
    check = today
    while check in published_dates:
        streak += 1
        check -= timedelta(days=1)

    logger.info(
        f"[insights] streak={streak} week_days={week_days} client={current_client.id}"
    )
    return StreakResponse(streak=streak, week_days=week_days, week_goal=5)


def _current_monday() -> date:
    """Retorna a segunda-feira da semana corrente."""
    today = date.today()
    return today - timedelta(days=today.weekday())


@router.get("/instagram")
async def get_instagram_analytics(
    current_client: Client = Depends(get_current_client),
):
    """
    Retorna métricas orgânicas da conta Instagram do client autenticado (últimos 30d).

    Dados: alcance total, série diária, crescimento de seguidores, engajamento.
    Cache Redis de 6h por client — evita consumo excessivo de cota da Graph API.
    """
    if not current_client.instagram_business_id:
        raise HTTPException(
            status_code=422,
            detail="Conta Instagram não conectada. Conecte sua conta nas configurações.",
        )
    if not current_client.meta_access_token:
        raise HTTPException(
            status_code=422,
            detail="Token Meta não configurado. Reconecte sua conta Instagram.",
        )

    cache_key = f"ig_analytics:{current_client.id}"
    redis = await get_redis()

    cached = await redis.get(cache_key)
    if cached:
        logger.info(f"[insights/instagram] cache hit client={current_client.id}")
        return json.loads(cached)

    data = await get_instagram_analytics_30d(
        ig_business_id=current_client.instagram_business_id,
        access_token=current_client.meta_access_token,
    )

    if "error" in data:
        status_code = 401 if data.get("code") == 190 else 502
        raise HTTPException(status_code=status_code, detail=data["error"])

    await redis.setex(cache_key, ANALYTICS_CACHE_TTL, json.dumps(data))
    logger.info(f"[insights/instagram] dados coletados client={current_client.id}")
    return data


def _normalize_segment(segment: str) -> str:
    """Normaliza segmento para matching: lowercase + remove acentos."""
    nfkd = unicodedata.normalize("NFKD", segment.lower().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


@router.get("/themes")
async def list_themes(
    current_client: Client = Depends(get_current_client),
):
    """Retorna temas de carrossel para o nicho do client autenticado."""
    brand_profile = current_client.brand_profile or {}
    raw_segment = brand_profile.get("segment", "")
    normalized = _normalize_segment(raw_segment)

    # Tenta matching exato normalizado
    matched_key = None
    for key in THEME_LIBRARY:
        if key == "default":
            continue
        if _normalize_segment(key) == normalized:
            matched_key = key
            break

    if matched_key:
        themes = THEME_LIBRARY[matched_key]
        segment_display = matched_key
    else:
        # Fallback: temas default
        themes = THEME_LIBRARY["default"]
        segment_display = raw_segment or "geral"

    return {"segment": segment_display, "themes": themes}
