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


def _theme_relevance_score(theme: dict, recurring_topics_normalized: list[str]) -> int:
    """
    Pontua um tema pelo overlap entre suas tags e os recurring_topics do
    Agente Scout (Epic 22, Story 22.4). Retorna 0 se não houver
    recurring_topics — garante que a ordenação fica idêntica à atual
    quando o Scout não rodou/pulou/falhou (AC3).
    """
    if not recurring_topics_normalized:
        return 0
    tags_normalized = [_normalize_segment(t) for t in (theme.get("tags") or []) if isinstance(t, str)]
    return sum(
        1
        for topic in recurring_topics_normalized
        for tag in tags_normalized
        if topic and tag and (topic in tag or tag in topic)
    )


@router.get("/themes")
async def list_themes(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna temas de carrossel para o nicho do client autenticado.
    Temas não usados aparecem primeiro; temas já publicados ficam por último.
    Multi-tenant: filtra exclusivamente pelo business_segment do brand_profile.
    """
    brand_profile = current_client.brand_profile or {}
    raw_segment   = brand_profile.get("segment", "")
    normalized    = _normalize_segment(raw_segment)

    # Matching por segmento do cliente (multi-tenant, sem hardcoding)
    matched_key = None
    for key in THEME_LIBRARY:
        if key == "default":
            continue
        if _normalize_segment(key) == normalized:
            matched_key = key
            break

    base_themes     = THEME_LIBRARY[matched_key] if matched_key else THEME_LIBRARY["default"]
    segment_display = matched_key if matched_key else (raw_segment or "geral")

    # Insights do Agente Scout (Epic 22, Story 22.4) — reordena por relevância
    # dentro do mesmo grupo de used_count. Lista vazia quando ausente/malformado
    # => relevância sempre 0 => ordenação idêntica à atual (AC3).
    scout_insights = brand_profile.get("scout_insights") or {}
    recurring_topics = scout_insights.get("recurring_topics") if isinstance(scout_insights, dict) else None
    recurring_topics_normalized = (
        [_normalize_segment(t) for t in recurring_topics if isinstance(t, str)]
        if isinstance(recurring_topics, list)
        else []
    )

    # Conta uso de cada tema por este cliente (apenas posts publicados)
    usage_result = await db.execute(
        select(ContentRequest.theme_id, func.count().label("cnt"))
        .where(
            ContentRequest.client_id == current_client.id,
            ContentRequest.theme_id.isnot(None),
            ContentRequest.status == ContentStatus.published,
        )
        .group_by(ContentRequest.theme_id)
    )
    usage_map: dict[str, int] = {row.theme_id: row.cnt for row in usage_result}

    # Enriquece temas com contagem e ordena: unused (0) primeiro,
    # e dentro do mesmo used_count, mais relevante ao Scout primeiro (Story 22.4)
    enriched = [
        {**t, "used_count": usage_map.get(t["id"], 0)}
        for t in base_themes
    ]
    enriched.sort(
        key=lambda t: (t["used_count"], -_theme_relevance_score(t, recurring_topics_normalized))
    )

    logger.info(
        f"[themes] client={current_client.id} segment={segment_display!r} "
        f"total={len(enriched)} unused={sum(1 for t in enriched if t['used_count'] == 0)}"
    )

    return {"segment": segment_display, "themes": enriched}


# ─── GET /insights/strategy-recommendation ───────────────────────────────────

# Fallback hardcoded (Story 18.2) — usado quando não há histórico suficiente
_FALLBACK_RECOMMENDATION: dict[str, dict[str, str]] = {
    "gerar_orcamentos":    {"feed_photo": "prova_social",         "carousel": "case_estudo",   "reels": "depoimento_video",      "story": "cta_link"},
    "ganhar_seguidores":   {"feed_photo": "ancora_de_marca",      "carousel": "erros_mitos",   "reels": "hook_choque",           "story": "repost_feed"},
    "aumentar_engajamento":{"feed_photo": "curiosidade_pergunta", "carousel": "comparativo",   "reels": "trend_nicho",           "story": "caixa_perguntas"},
    "construir_autoridade":{"feed_photo": "bastidores",           "carousel": "passo_a_passo", "reels": "tutorial_pov",          "story": "bastidores_dia"},
    "manter_ativo":        {"feed_photo": "hero_shot",            "carousel": "checklist",     "reels": "bastidores_autenticos", "story": "bastidores_dia"},
}

_MIN_HISTORY = 3  # mínimo de posts publicados neste formato para usar dados reais


@router.get("/strategy-recommendation")
async def get_strategy_recommendation(
    intent: str,
    format: str,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Retorna a estratégia recomendada para a combinação intent+formato.

    Lógica data-driven (Story 18.2):
    1. Busca posts publicados deste cliente com o formato solicitado
    2. Conta estratégias usadas — a mais frequente indica preferência validada
    3. Se histórico >= MIN_HISTORY posts no formato: usa a estratégia mais usada
    4. Fallback: retorna a recomendação editorial hardcoded
    """
    fallback_by_format = _FALLBACK_RECOMMENDATION.get(intent, {})
    fallback_strategy  = fallback_by_format.get(format)

    if not fallback_strategy:
        raise HTTPException(status_code=422, detail=f"intent ou format inválido: {intent!r} / {format!r}")

    # Histórico de posts publicados neste formato
    history_result = await db.execute(
        select(ContentRequest.strategy, func.count().label("cnt"))
        .where(
            ContentRequest.client_id   == current_client.id,
            ContentRequest.content_type == format,
            ContentRequest.status       == ContentStatus.published,
            ContentRequest.strategy.isnot(None),
        )
        .group_by(ContentRequest.strategy)
        .order_by(desc("cnt"))
    )
    rows = history_result.fetchall()
    total_in_format = sum(r.cnt for r in rows)

    if total_in_format >= _MIN_HISTORY and rows:
        # Usa a estratégia mais publicada neste formato como recomendação
        top_strategy = rows[0].strategy
        source       = "history"
        logger.info(
            f"[recommendation] client={current_client.id} intent={intent!r} format={format!r} "
            f"→ {top_strategy!r} (data-driven, {total_in_format} posts)"
        )
    else:
        top_strategy = fallback_strategy
        source       = "editorial"
        logger.info(
            f"[recommendation] client={current_client.id} intent={intent!r} format={format!r} "
            f"→ {top_strategy!r} (fallback editorial, apenas {total_in_format} posts no formato)"
        )

    return {
        "intent":    intent,
        "format":    format,
        "strategy":  top_strategy,
        "source":    source,
        "history_count": total_in_format,
    }
