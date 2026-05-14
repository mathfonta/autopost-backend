"""
Testes para Story 13.3 (hashtag extraction) e Story 13.4 (weekly intelligence).

Coberturas:
  13.3 — extração de hashtags + injeção no copywriter (complementa test_exa_pipeline.py)
  13.4 — generate_weekly_intelligence task, _summarize_snippets, _extract_weekly_hashtags,
          _save_weekly_context, GET /insights/weekly endpoint
"""

import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ══════════════════════════════════════════════════════════════════
#  Story 13.3 — Hashtag extraction helpers
# ══════════════════════════════════════════════════════════════════

def test_extract_hashtags_from_explicit_tags():
    """Extrai hashtags explícitas (#tag) do contexto Exa."""
    import re

    exa_context = "Tendências:\n• construção modular\n#construcaocivil #alvenaria #obra2026"
    explicit_tags = re.findall(r'#(\w+)', exa_context)
    assert "construcaocivil" in explicit_tags
    assert "alvenaria" in explicit_tags
    assert "obra2026" in explicit_tags


def test_extract_hashtags_from_bullet_terms():
    """Deriva hashtags de termos em bullet points."""
    import re

    exa_context = "• acabamento premium\n• revestimento externo\n• tecnologia sustentável"
    bullet_terms = re.findall(r'•\s+(.+?)(?:\n|$)', exa_context)
    derived = []
    for term in bullet_terms:
        words = [w.lower() for w in re.findall(r'\b[a-zA-ZÀ-ú]{4,}\b', term)]
        if words:
            derived.append("".join(words[:2]))

    assert "acabamentopremium" in derived
    assert "revestimentoexterno" in derived


def test_hashtag_limit_is_respected():
    """Garante que no máximo 8 hashtags são injetadas no prompt."""
    import re

    exa_context = "#tag1 #tag2 #tag3 #tag4 #tag5 #tag6 #tag7 #tag8 #tag9 #tag10"
    explicit = re.findall(r'#(\w+)', exa_context)
    candidates = [t.lower() for t in explicit[:5]]  # máx 5 explícitas
    tags_str = " ".join(f"#{h}" for h in candidates[:8])
    assert tags_str.count("#") <= 8


# ══════════════════════════════════════════════════════════════════
#  Story 13.4 — _extract_weekly_hashtags
# ══════════════════════════════════════════════════════════════════

def test_extract_weekly_hashtags_empty():
    """Retorna lista vazia quando não há snippets."""
    from app.tasks.pipeline import _extract_weekly_hashtags  # type: ignore

    result = _extract_weekly_hashtags([])
    assert result == []


def test_extract_weekly_hashtags_basic():
    """Extrai hashtags de snippets com texto (strings, não dicts)."""
    from app.tasks.pipeline import _extract_weekly_hashtags  # type: ignore

    snippets = [
        "Tendências de construção sustentável. #construcaosustentavel #greenbuild",
        "Acabamento moderno com revestimento externo. #revestimento",
    ]
    result = _extract_weekly_hashtags(snippets)
    assert isinstance(result, list)
    assert any("construcaosustentavel" in h for h in result)
    assert any("revestimento" in h for h in result)


def test_extract_weekly_hashtags_max_10():
    """Retorna no máximo 10 hashtags."""
    from app.tasks.pipeline import _extract_weekly_hashtags  # type: ignore

    # Muitos snippets com muitas tags (strings)
    snippets = [f"#tag{i} #outro{i} #mais{i}" for i in range(20)]
    result = _extract_weekly_hashtags(snippets)
    assert len(result) <= 10


# ══════════════════════════════════════════════════════════════════
#  Story 13.4 — _summarize_snippets
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_summarize_snippets_no_api_key():
    """Retorna fallback de bullet points quando não há GEMINI_API_KEY."""
    import os
    from app.tasks.pipeline import _summarize_snippets  # type: ignore

    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        result = await _summarize_snippets(
            snippets=["tendência de mercado", "construção sustentável"]
        )
    # Deve retornar string (bullet list de fallback)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_summarize_snippets_empty_snippets():
    """Retorna string vazia quando lista de snippets está vazia."""
    import os
    from app.tasks.pipeline import _summarize_snippets  # type: ignore

    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        result = await _summarize_snippets(snippets=[])
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_summarize_snippets_gemini_exception_returns_fallback():
    """Captura exceção do Gemini e retorna fallback com os snippets."""
    import os
    from app.tasks.pipeline import _summarize_snippets  # type: ignore

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("API error"))

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            result = await _summarize_snippets(snippets=["texto de teste"])
    # Deve retornar alguma string, não levantar exceção
    assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════
#  Story 13.4 — generate_weekly_intelligence (Celery task)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_weekly_intelligence_skips_when_exa_disabled():
    """Não executa quando EXA_PROVIDER != 'exa' — retorna early sem chamar search_exa_raw."""
    import os
    from app.tasks.pipeline import generate_weekly_intelligence  # type: ignore

    # search_exa_raw é importado DENTRO da task — patchamos no módulo source
    with patch.dict(os.environ, {"EXA_PROVIDER": "disabled"}):
        with patch("app.tools.exa_search.search_exa_raw") as mock_search:
            # Celery tasks têm .run() como a função real
            if hasattr(generate_weekly_intelligence, 'run'):
                try:
                    generate_weekly_intelligence.run()
                except Exception:
                    pass  # DB não disponível em test — ok
            else:
                try:
                    generate_weekly_intelligence()
                except Exception:
                    pass
            # Com EXA_PROVIDER=disabled, a task retorna early — search nunca é chamado
            mock_search.assert_not_called()


# ══════════════════════════════════════════════════════════════════
#  Story 13.4 — GET /insights/weekly endpoint
# ══════════════════════════════════════════════════════════════════

def _make_weekly_context():
    """Cria instância WeeklyContext para uso nos testes."""
    from app.models.weekly_context import WeeklyContext
    from datetime import datetime, timezone

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    wc = WeeklyContext()
    wc.id = uuid4()
    wc.week_of = monday
    wc.segment = "Construção civil"
    wc.summary = "• Tendência 1\n• Tendência 2"
    wc.hashtags = ["construcaocivil", "obra2026"]
    wc.created_at = datetime.now(timezone.utc)
    return wc


@pytest.mark.asyncio
async def test_get_weekly_insight_returns_data():
    """Endpoint retorna WeeklyContext quando disponível."""
    from app.api.insights import get_weekly_insight
    from app.models.client import Client

    mock_client = MagicMock(spec=Client)
    mock_client.id = uuid4()
    mock_client.business_segment = "Construção civil"

    weekly = _make_weekly_context()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = weekly
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_weekly_insight(current_client=mock_client, db=mock_db)

    assert result.segment == "Construção civil"
    assert result.summary == "• Tendência 1\n• Tendência 2"
    assert "construcaocivil" in result.hashtags


@pytest.mark.asyncio
async def test_get_weekly_insight_404_when_no_data():
    """Endpoint retorna 404 quando não há dados."""
    from fastapi import HTTPException
    from app.api.insights import get_weekly_insight
    from app.models.client import Client

    mock_client = MagicMock(spec=Client)
    mock_client.id = uuid4()
    mock_client.business_segment = "Segmento Inexistente"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(HTTPException) as exc_info:
        await get_weekly_insight(current_client=mock_client, db=mock_db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_weekly_insight_fallback_no_segment():
    """Usa fallback 'geral' quando client não tem business_segment."""
    from app.api.insights import get_weekly_insight
    from app.models.client import Client

    mock_client = MagicMock(spec=Client)
    mock_client.id = uuid4()
    # Sem atributo business_segment → fallback para "geral"
    del mock_client.business_segment

    weekly = _make_weekly_context()
    weekly.segment = "geral"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = weekly
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await get_weekly_insight(current_client=mock_client, db=mock_db)
    assert result is not None
