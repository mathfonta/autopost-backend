"""
Testes do endpoint GET /insights/best-posting-time (Epic 19, Story 19.3).
Não conecta ao banco real — usa mocks.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def _mock_client(segment="construção civil"):
    client = MagicMock()
    client.id = uuid4()
    client.brand_profile = {"segment": segment}
    return client


def _publish_result(hour_utc: int, likes=0, comments=0, reach=0, day_offset=0):
    """Simula publish_result de um post publicado numa hora específica (UTC)."""
    published_at = (
        datetime.now(timezone.utc).replace(hour=hour_utc, minute=0, second=0, microsecond=0)
        - timedelta(days=day_offset)
    )
    return {
        "published_at": published_at.isoformat(),
        "metrics": {"likes": likes, "comments": comments, "reach": reach},
    }


def _mock_db(
    publish_results: list[dict],
    weekly_suggested_time: str | None = None,
    weekly_segment: str = "construção civil",
):
    """Mock de AsyncSession: 1ª chamada = histórico (fetchall), 2ª = weekly_context (fetchall)."""
    history_result = MagicMock()
    history_result.fetchall.return_value = [(pr,) for pr in publish_results]

    weekly_result = MagicMock()
    weekly_rows = [(weekly_segment, weekly_suggested_time)] if weekly_suggested_time else []
    weekly_result.fetchall.return_value = weekly_rows

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[history_result, weekly_result])
    return db


@pytest.mark.asyncio
async def test_best_posting_time_uses_historico_when_enough_data():
    """AC2 — com >=5 posts e hora vencedora com >=2 posts, usa histórico."""
    from app.api.insights import get_best_posting_time

    # Hora 22 UTC (19h em São Paulo, UTC-3) com maior engajamento, 2 posts
    posts = [
        _publish_result(22, likes=100, comments=20, reach=500, day_offset=1),
        _publish_result(22, likes=90, comments=15, reach=400, day_offset=8),
        _publish_result(12, likes=10, comments=1, reach=50, day_offset=2),
        _publish_result(12, likes=5, comments=0, reach=20, day_offset=9),
        _publish_result(9, likes=3, comments=0, reach=10, day_offset=3),
    ]
    db = _mock_db(posts)
    client = _mock_client()

    result = await get_best_posting_time(format=None, current_client=client, db=db)

    assert result.fonte == "historico"
    assert result.confianca == "alta"
    assert result.horario == "19:00"


@pytest.mark.asyncio
async def test_best_posting_time_density_guard_falls_through():
    """AC3 — hora vencedora com só 1 post (mesmo com >=5 posts totais) não conta;
    sem Exa disponível, cai no fallback estático."""
    from app.api.insights import get_best_posting_time

    posts = [
        _publish_result(22, likes=1000, comments=100, reach=5000, day_offset=1),  # 1 post só
        _publish_result(12, likes=10, comments=1, reach=50, day_offset=2),
        _publish_result(12, likes=8, comments=1, reach=40, day_offset=9),
        _publish_result(9, likes=3, comments=0, reach=10, day_offset=3),
        _publish_result(9, likes=2, comments=0, reach=8, day_offset=10),
    ]
    db = _mock_db(posts, weekly_suggested_time=None)
    client = _mock_client()

    result = await get_best_posting_time(format=None, current_client=client, db=db)

    assert result.fonte == "fallback"
    assert result.confianca == "baixa"


@pytest.mark.asyncio
async def test_best_posting_time_below_threshold_uses_exa():
    """AC4 — com <5 posts publicados, mas WeeklyContext.suggested_time disponível → fonte exa."""
    from app.api.insights import get_best_posting_time

    posts = [_publish_result(12, likes=10, comments=1, reach=50)]
    db = _mock_db(posts, weekly_suggested_time="20:00")
    client = _mock_client()

    result = await get_best_posting_time(format=None, current_client=client, db=db)

    assert result.fonte == "exa"
    assert result.confianca == "media"
    assert result.horario == "20:00"


@pytest.mark.asyncio
async def test_best_posting_time_exa_matches_despite_case_difference():
    """BUG-001 (achado do QA) — client.brand_profile.segment ("construção civil",
    minúsculo, texto livre do onboarding) deve casar com WeeklyContext.segment
    ("Construção civil", capital C, hardcoded em generate_weekly_intelligence).
    Antes da correção, essa comparação exata falhava silenciosamente."""
    from app.api.insights import get_best_posting_time

    db = _mock_db(
        [],
        weekly_suggested_time="20:00",
        weekly_segment="Construção civil",  # capital C, como salvo pela task
    )
    client = _mock_client(segment="construção civil")  # minúsculo, como o resto do código usa

    result = await get_best_posting_time(format=None, current_client=client, db=db)

    assert result.fonte == "exa"
    assert result.horario == "20:00"


@pytest.mark.asyncio
async def test_best_posting_time_fallback_when_no_data():
    """AC5 — sem histórico suficiente e sem Exa → fallback _DEFAULT_TIMES por segmento."""
    from app.api.insights import get_best_posting_time

    db = _mock_db([], weekly_suggested_time=None)
    client = _mock_client(segment="construção civil")

    result = await get_best_posting_time(format=None, current_client=client, db=db)

    assert result.fonte == "fallback"
    assert result.confianca == "baixa"
    assert result.horario == "18:00"  # _DEFAULT_TIMES["construção civil"]


@pytest.mark.asyncio
async def test_best_posting_time_fallback_unknown_segment_uses_default():
    """Segmento fora da tabela usa _DEFAULT_TIMES["default"]."""
    from app.api.insights import get_best_posting_time

    db = _mock_db([], weekly_suggested_time=None)
    client = _mock_client(segment="segmento nunca visto")

    result = await get_best_posting_time(format=None, current_client=client, db=db)

    assert result.fonte == "fallback"
    assert result.horario == "19:00"  # _DEFAULT_TIMES["default"]
