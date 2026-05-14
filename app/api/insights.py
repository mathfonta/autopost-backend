"""
Endpoints de inteligência de mercado (Story 13.4).

GET /insights/weekly  — retorna o último WeeklyContext disponível
                        para o segmento do client autenticado
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_client
from app.core.database import get_db
from app.models.client import Client
from app.models.content_request import ContentRequest, ContentStatus
from app.models.weekly_context import WeeklyContext
from app.schemas.weekly_context import WeeklyContextResponse, StreakResponse

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
