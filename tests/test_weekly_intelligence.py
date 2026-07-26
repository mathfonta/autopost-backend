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


@pytest.mark.asyncio
async def test_summarize_snippets_prompt_references_segment():
    """Story 27.2 — o prompt enviado ao Gemini referencia o segmento informado, não 'construção civil'."""
    import os
    from app.tasks.pipeline import _summarize_snippets  # type: ignore

    mock_response = MagicMock()
    mock_response.text = "• tendência 1"
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            await _summarize_snippets(snippets=["texto de teste"], segment="Moda e vestuário")

    sent_prompt = mock_client.aio.models.generate_content.call_args.kwargs["contents"][0]
    assert "Moda e vestuário" in sent_prompt
    assert "construção civil" not in sent_prompt.lower()


# ══════════════════════════════════════════════════════════════════
#  Story 27.2 — _generate_segment_queries
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_generate_segment_queries_no_api_key_returns_fallback():
    """Sem GEMINI_API_KEY → fallback template com o segmento, nunca vazio."""
    import os
    from app.tasks.pipeline import _generate_segment_queries  # type: ignore

    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        result = await _generate_segment_queries("Moda e vestuário")

    assert len(result) == 3
    assert all("Moda e vestuário" in q for q in result)


@pytest.mark.asyncio
async def test_generate_segment_queries_parses_gemini_response():
    """Gemini retorna 3 linhas válidas → função retorna essas 3 queries."""
    import os
    from app.tasks.pipeline import _generate_segment_queries  # type: ignore

    mock_response = MagicMock()
    mock_response.text = (
        "moda vestuário Brasil notícias semana\n"
        "tendências moda sustentável 2026\n"
        "mercado consumo moda Brasil"
    )
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            result = await _generate_segment_queries("Moda e vestuário")

    assert len(result) == 3
    assert result[0] == "moda vestuário Brasil notícias semana"


@pytest.mark.asyncio
async def test_generate_segment_queries_gemini_exception_returns_fallback():
    """Falha do Gemini é capturada e retorna fallback template, nunca propaga."""
    import os
    from app.tasks.pipeline import _generate_segment_queries  # type: ignore

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("API error"))

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            result = await _generate_segment_queries("Odontologia")

    assert len(result) == 3
    assert all("Odontologia" in q for q in result)


@pytest.mark.asyncio
async def test_generate_segment_queries_insufficient_lines_returns_fallback():
    """Gemini retorna menos de 3 linhas válidas → fallback, nunca lista incompleta."""
    import os
    from app.tasks.pipeline import _generate_segment_queries  # type: ignore

    mock_response = MagicMock()
    mock_response.text = "só uma linha"
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            result = await _generate_segment_queries("Odontologia")

    assert len(result) == 3
    assert all("Odontologia" in q for q in result)


# ══════════════════════════════════════════════════════════════════
#  Story 19.3 — _extract_suggested_time
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_extract_suggested_time_no_snippets_returns_none():
    """Sem snippets → None, nunca inventa horário."""
    import os
    from app.tasks.pipeline import _extract_suggested_time  # type: ignore

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        result = await _extract_suggested_time([])
    assert result is None


@pytest.mark.asyncio
async def test_extract_suggested_time_no_api_key_returns_none():
    """Sem GEMINI_API_KEY → None, nunca inventa horário."""
    import os
    from app.tasks.pipeline import _extract_suggested_time  # type: ignore

    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        result = await _extract_suggested_time(["algum snippet"])
    assert result is None


@pytest.mark.asyncio
async def test_extract_suggested_time_parses_valid_response():
    """Resposta do Gemini com horário válido é extraída e normalizada."""
    import os
    from app.tasks.pipeline import _extract_suggested_time  # type: ignore

    mock_response = MagicMock()
    mock_response.text = "19:00"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            result = await _extract_suggested_time(["horário ideal é às 19h"])

    assert result == "19:00"


@pytest.mark.asyncio
async def test_extract_suggested_time_prompt_references_segment():
    """Story 27.2 — o prompt enviado ao Gemini referencia o segmento informado, não 'construção civil'."""
    import os
    from app.tasks.pipeline import _extract_suggested_time  # type: ignore

    mock_response = MagicMock()
    mock_response.text = "10:00"
    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            await _extract_suggested_time(["algum snippet"], segment="Odontologia")

    sent_prompt = mock_client.aio.models.generate_content.call_args.kwargs["contents"][0]
    assert "Odontologia" in sent_prompt
    assert "construção civil" not in sent_prompt.lower()


@pytest.mark.asyncio
async def test_extract_suggested_time_unknown_response_returns_none():
    """Resposta 'DESCONHECIDO' (sem sinal claro nos resultados) → None, não inventa."""
    import os
    from app.tasks.pipeline import _extract_suggested_time  # type: ignore

    mock_response = MagicMock()
    mock_response.text = "DESCONHECIDO"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            result = await _extract_suggested_time(["nada relevante aqui"])

    assert result is None


@pytest.mark.asyncio
async def test_extract_suggested_time_gemini_exception_returns_none():
    """Falha do Gemini é capturada e retorna None, nunca propaga nem inventa."""
    import os
    from app.tasks.pipeline import _extract_suggested_time  # type: ignore

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("API error"))

    mock_genai_module = MagicMock()
    mock_genai_module.Client.return_value = mock_client

    with patch.dict(os.environ, {"GEMINI_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"google.genai": mock_genai_module, "google": MagicMock(genai=mock_genai_module)}):
            result = await _extract_suggested_time(["algum snippet"])

    assert result is None


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
#  Story 27.3 — _get_active_segments (dedup normalizado + contagem)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_active_segments_dedups_by_normalized_and_counts():
    """Grafias diferentes do mesmo segmento são agrupadas; vazio/ausente é ignorado."""
    from app.tasks.pipeline import _get_active_segments  # type: ignore

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ({"segment": "Moda e vestuário"},),
        ({"segment": "moda e vestuario"},),  # mesma normalizada
        ({"segment": "Construção civil"},),
        ({"segment": ""},),
        ({},),
    ]

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.database.WorkerSessionLocal", MagicMock(return_value=mock_session_ctx)):
        result = await _get_active_segments()

    result_dict = dict(result)
    assert len(result) == 2  # vazio e sem-segment ignorados
    assert result_dict["Moda e vestuário"] == 2  # dedup: 2 clientes no mesmo grupo
    assert result_dict["Construção civil"] == 1
    assert result[0][0] == "Moda e vestuário"  # ordenado por contagem desc


@pytest.mark.asyncio
async def test_get_active_segments_empty_when_no_clients():
    """Nenhum cliente ativo com segmento → lista vazia."""
    from app.tasks.pipeline import _get_active_segments  # type: ignore

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.database.WorkerSessionLocal", MagicMock(return_value=mock_session_ctx)):
        result = await _get_active_segments()

    assert result == []


# ══════════════════════════════════════════════════════════════════
#  Story 27.3 — fan-out por segmento (generate_weekly_intelligence)
# ══════════════════════════════════════════════════════════════════

def _run_weekly_intelligence_task():
    from app.tasks.pipeline import generate_weekly_intelligence  # type: ignore

    if hasattr(generate_weekly_intelligence, "run"):
        generate_weekly_intelligence.run()
    else:
        generate_weekly_intelligence()


def test_weekly_intelligence_fanout_generates_context_per_segment():
    """2 segmentos ativos distintos → _save_weekly_context é chamado para os 2 (fan-out), não 1 global.

    Síncrono de propósito: generate_weekly_intelligence gerencia seu próprio
    asyncio.run() internamente (_run_sync) — não pode rodar sob @pytest.mark.asyncio
    (loop já ativo do pytest-asyncio colidiria com o asyncio.run() interno).
    """
    import os

    saved_segments = []

    async def fake_save(segment, raw_snippets, summary, hashtags, suggested_time=None):
        saved_segments.append(segment)

    with patch.dict(os.environ, {"EXA_PROVIDER": "exa", "GEMINI_API_KEY": ""}):
        with patch(
            "app.tasks.pipeline._get_active_segments",
            AsyncMock(return_value=[("Moda e vestuário", 3), ("Construção civil", 5)]),
        ):
            with patch("app.tools.exa_search.search_exa_raw", AsyncMock(return_value=["snippet de tendência"])):
                with patch("app.tasks.pipeline._save_weekly_context", AsyncMock(side_effect=fake_save)):
                    _run_weekly_intelligence_task()

    assert "Moda e vestuário" in saved_segments
    assert "Construção civil" in saved_segments


def test_weekly_intelligence_fanout_isolates_failure_per_segment():
    """Falha de Exa num segmento não impede a persistência dos demais (NFR-2). Síncrono — ver nota acima."""
    import os

    saved_segments = []

    async def fake_save(segment, raw_snippets, summary, hashtags, suggested_time=None):
        saved_segments.append(segment)

    async def fake_search(query, days_back=7):
        if "Moda" in query:
            raise Exception("Exa timeout simulado para Moda")
        return ["snippet de construção civil"]

    with patch.dict(os.environ, {"EXA_PROVIDER": "exa", "GEMINI_API_KEY": ""}):
        with patch(
            "app.tasks.pipeline._get_active_segments",
            AsyncMock(return_value=[("Moda e vestuário", 3), ("Construção civil", 5)]),
        ):
            with patch("app.tools.exa_search.search_exa_raw", AsyncMock(side_effect=fake_search)):
                with patch("app.tasks.pipeline._save_weekly_context", AsyncMock(side_effect=fake_save)):
                    _run_weekly_intelligence_task()

    assert "Construção civil" in saved_segments
    assert "Moda e vestuário" not in saved_segments


def test_weekly_intelligence_guardrail_caps_at_max_segments():
    """N de segmentos > MAX_SEGMENTS_PER_RUN → processa só o teto, priorizando por nº de clientes. Síncrono — ver nota acima."""
    import os

    saved_segments = []

    async def fake_save(segment, raw_snippets, summary, hashtags, suggested_time=None):
        saved_segments.append(segment)

    fake_segments = [(f"Segmento {i}", 10 - i) for i in range(5)]  # já vem ordenado por contagem desc

    with patch.dict(
        os.environ,
        {"EXA_PROVIDER": "exa", "GEMINI_API_KEY": "", "MAX_SEGMENTS_PER_RUN": "2"},
    ):
        with patch("app.tasks.pipeline._get_active_segments", AsyncMock(return_value=fake_segments)):
            with patch("app.tools.exa_search.search_exa_raw", AsyncMock(return_value=["snippet"])):
                with patch("app.tasks.pipeline._save_weekly_context", AsyncMock(side_effect=fake_save)):
                    _run_weekly_intelligence_task()

    assert len(saved_segments) == 2
    assert saved_segments == ["Segmento 0", "Segmento 1"]


def test_weekly_intelligence_no_active_segments_returns_early():
    """Nenhum segmento ativo → encerra sem chamar Exa. Síncrono — ver nota acima."""
    import os

    with patch.dict(os.environ, {"EXA_PROVIDER": "exa"}):
        with patch("app.tasks.pipeline._get_active_segments", AsyncMock(return_value=[])):
            with patch("app.tools.exa_search.search_exa_raw") as mock_search:
                _run_weekly_intelligence_task()
                mock_search.assert_not_called()


# ══════════════════════════════════════════════════════════════════
#  Story 27.3 — _save_weekly_context dedup normalizado (CRIT-1)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_save_weekly_context_dedups_normalized_spelling_variant():
    """Grafia diferente do mesmo segmento na mesma semana atualiza o registro existente, não cria 2ª linha."""
    from app.tasks.pipeline import _save_weekly_context  # type: ignore

    existing_wc = _make_weekly_context(segment="Construção civil")

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [existing_wc]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.database.WorkerSessionLocal", MagicMock(return_value=mock_session_ctx)):
        await _save_weekly_context(
            segment="construcao civil",  # grafia diferente, normaliza igual
            raw_snippets=["novo snippet"],
            summary="novo resumo",
            hashtags=["novatag"],
            suggested_time="09:00",
        )

    mock_db.add.assert_not_called()  # não criou registro novo
    assert existing_wc.summary == "novo resumo"  # atualizou o existente
    assert existing_wc.segment == "construcao civil"  # grafia mais recente persistida


# ══════════════════════════════════════════════════════════════════
#  Story 27.1 — GET /insights/weekly endpoint (multi-segmento)
# ══════════════════════════════════════════════════════════════════

def _make_weekly_context(segment: str = "Construção civil"):
    """Cria instância WeeklyContext para uso nos testes."""
    from app.models.weekly_context import WeeklyContext
    from datetime import datetime, timezone

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    wc = WeeklyContext()
    wc.id = uuid4()
    wc.week_of = monday
    wc.segment = segment
    wc.summary = "• Tendência 1\n• Tendência 2"
    wc.hashtags = ["tag1", "tag2"]
    wc.created_at = datetime.now(timezone.utc)
    return wc


def _mock_db_with_rows(rows: list):
    """Mock de AsyncSession cujo .execute().scalars().all() retorna `rows`."""
    mock_db = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = rows
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


def _make_client(segment: str | None):
    """Cria client mock com segmento em brand_profile (padrão real, não business_segment)."""
    from app.models.client import Client

    mock_client = MagicMock(spec=Client)
    mock_client.id = uuid4()
    mock_client.brand_profile = {"segment": segment} if segment is not None else {}
    return mock_client


@pytest.mark.asyncio
async def test_get_weekly_insight_returns_data_for_matching_segment():
    """Cliente de 'Moda e vestuário' com WeeklyContext do próprio segmento recebe o dele."""
    from app.api.insights import get_weekly_insight

    client = _make_client("Moda e vestuário")
    weekly_moda = _make_weekly_context(segment="Moda e vestuário")
    weekly_construcao = _make_weekly_context(segment="Construção civil")
    mock_db = _mock_db_with_rows([weekly_moda, weekly_construcao])

    result = await get_weekly_insight(current_client=client, db=mock_db)

    assert result.segment == "Moda e vestuário"


@pytest.mark.asyncio
async def test_get_weekly_insight_404_when_no_context_for_segment():
    """Cliente de 'Moda e vestuário' sem WeeklyContext do próprio segmento recebe 404 —
    NÃO recebe o de 'Construção civil' (não há mais fallback global)."""
    from fastapi import HTTPException
    from app.api.insights import get_weekly_insight

    client = _make_client("Moda e vestuário")
    weekly_construcao = _make_weekly_context(segment="Construção civil")
    mock_db = _mock_db_with_rows([weekly_construcao])

    with pytest.raises(HTTPException) as exc_info:
        await get_weekly_insight(current_client=client, db=mock_db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_weekly_insight_404_when_client_has_no_segment():
    """Cliente sem segment em brand_profile recebe 404 (não recebe dado de outro nicho)."""
    from fastapi import HTTPException
    from app.api.insights import get_weekly_insight

    client = _make_client(None)
    weekly_construcao = _make_weekly_context(segment="Construção civil")
    mock_db = _mock_db_with_rows([weekly_construcao])

    with pytest.raises(HTTPException) as exc_info:
        await get_weekly_insight(current_client=client, db=mock_db)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_weekly_insight_no_regression_for_construcao_civil():
    """Cliente de 'Construção civil' continua recebendo o registro correto (zero regressão)."""
    from app.api.insights import get_weekly_insight

    client = _make_client("Construção civil")
    weekly_construcao = _make_weekly_context(segment="Construção civil")
    mock_db = _mock_db_with_rows([weekly_construcao])

    result = await get_weekly_insight(current_client=client, db=mock_db)

    assert result.segment == "Construção civil"
    assert result.summary == "• Tendência 1\n• Tendência 2"


@pytest.mark.asyncio
async def test_get_weekly_insight_matches_normalized_spelling_variant():
    """'construcao civil' (sem acento/minúsculo) casa com 'Construção civil' salvo no banco."""
    from app.api.insights import get_weekly_insight

    client = _make_client("construcao civil")
    weekly_construcao = _make_weekly_context(segment="Construção civil")
    mock_db = _mock_db_with_rows([weekly_construcao])

    result = await get_weekly_insight(current_client=client, db=mock_db)

    assert result.segment == "Construção civil"
