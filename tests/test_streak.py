"""
Testes para Story 14.3 — Streak semanal funcional.

Coberturas (AC6):
  - Semana com 3 dias publicados
  - Streak zero (nenhuma publicação)
  - Streak contínuo retroativo (publicações em dias consecutivos)
  - week_days reflete corretamente os dias da semana atual
  - Endpoint retorna 200 com dados corretos
"""

import pytest
from datetime import date, timedelta, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ══════════════════════════════════════════════════════════════════
#  Helpers: lógica pura de cálculo de streak
# ══════════════════════════════════════════════════════════════════

def _compute_streak(published_dates: set, today: date) -> int:
    """Replica a lógica do endpoint para testes unitários isolados."""
    streak = 0
    check = today
    while check in published_dates:
        streak += 1
        check -= timedelta(days=1)
    return streak


def _compute_week_days(published_dates: set, today: date) -> list[bool]:
    monday = today - timedelta(days=today.weekday())
    return [(monday + timedelta(days=i)) in published_dates for i in range(7)]


# ── AC6: streak zero ──────────────────────────────────────────────

def test_streak_zero_sem_publicacoes():
    today = date(2026, 5, 14)  # quarta
    assert _compute_streak(set(), today) == 0


def test_streak_zero_sem_publicacao_hoje():
    today = date(2026, 5, 14)
    # Publicou ontem mas não hoje — streak = 0 (ontem não conta sem hoje)
    published = {today - timedelta(days=1)}
    assert _compute_streak(published, today) == 0


# ── AC6: streak com dias consecutivos ────────────────────────────

def test_streak_um_dia_hoje():
    today = date(2026, 5, 14)
    published = {today}
    assert _compute_streak(published, today) == 1


def test_streak_tres_dias_consecutivos():
    today = date(2026, 5, 14)
    published = {today, today - timedelta(1), today - timedelta(2)}
    assert _compute_streak(published, today) == 3


def test_streak_nao_conta_dia_com_gap():
    today = date(2026, 5, 14)
    # Hoje e anteontem, mas sem ontem → streak = 1
    published = {today, today - timedelta(2)}
    assert _compute_streak(published, today) == 1


def test_streak_semanas_consecutivas():
    today = date(2026, 5, 14)
    # 10 dias seguidos terminando hoje
    published = {today - timedelta(i) for i in range(10)}
    assert _compute_streak(published, today) == 10


# ── AC6: week_days ────────────────────────────────────────────────

def test_week_days_tres_dias():
    # Semana de 11/05 (seg) a 17/05 (dom), publicou seg/ter/qua
    today = date(2026, 5, 13)  # quarta (weekday=2)
    monday = date(2026, 5, 11)
    published = {monday, monday + timedelta(1), monday + timedelta(2)}
    result = _compute_week_days(published, today)
    assert result == [True, True, True, False, False, False, False]


def test_week_days_sem_publicacoes():
    today = date(2026, 5, 14)
    result = _compute_week_days(set(), today)
    assert result == [False] * 7


def test_week_days_fim_de_semana():
    today = date(2026, 5, 16)  # sábado (weekday=5)
    monday = date(2026, 5, 11)
    published = {monday + timedelta(5)}  # sábado = 2026-05-16
    result = _compute_week_days(published, today)
    assert result[5] is True
    assert result[6] is False  # domingo não publicado


# ── AC1/AC5: endpoint HTTP ────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_streak_endpoint_sem_publicacoes():
    """Endpoint retorna streak=0 e week_days todos False quando não há posts."""
    from app.api.insights import get_streak

    mock_client = MagicMock()
    mock_client.id = uuid4()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.api.insights.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 14)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        response = await get_streak(current_client=mock_client, db=mock_db)

    assert response.streak == 0
    assert response.week_days == [False] * 7
    assert response.week_goal == 5


@pytest.mark.asyncio
async def test_get_streak_endpoint_com_publicacoes():
    """Endpoint retorna streak=2 quando publicou hoje e ontem."""
    from app.api.insights import get_streak

    today = date(2026, 5, 14)
    yesterday = today - timedelta(days=1)

    mock_client = MagicMock()
    mock_client.id = uuid4()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        (datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),),
        (datetime(2026, 5, 13, 15, 0, tzinfo=timezone.utc),),
    ]
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.api.insights.date") as mock_date:
        mock_date.today.return_value = today
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        response = await get_streak(current_client=mock_client, db=mock_db)

    assert response.streak == 2
    assert response.week_goal == 5
