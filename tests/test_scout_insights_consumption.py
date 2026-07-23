"""
Testes de consumo de scout_insights pelos agentes a jusante (Story 22.4).

Cobre AC5: geração COM scout_insights (prompt contém os insights),
geração SEM (idêntico ao comportamento atual), e scout_insights
parcial/malformado (não quebra) — para copywriter, theme_generator
e a reordenação de temas em app/api/insights.py.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.copywriter import generate_copy_with_ai
from app.agents.theme_generator import generate_slide_structure
from app.api.insights import _theme_relevance_score


# ─── Helpers ────────────────────────────────────────────────────

def _content_to_str(content) -> str:
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def _mock_claude_response(content: dict | str) -> MagicMock:
    message = MagicMock()
    message.content = [MagicMock()]
    message.content[0].text = content if isinstance(content, str) else json.dumps(content)
    return message


ANALYSIS = {
    "quality": "good",
    "content_type": "obra_realizada",
    "description": "Cozinha planejada finalizada em madeira clara.",
    "publish_clean": True,
    "stage": "acabamento",
}

BASE_BRAND = {
    "segment": "comércio",
    "tone": "profissional",
    "city": "Florianópolis",
    "company_name": "Marcenaria Silva",
}

SCOUT_INSIGHTS = {
    "refined_niche": "móveis planejados sob medida",
    "recurring_topics": ["cozinhas planejadas", "processo de marcenaria"],
    "visual_style": "ambientes finalizados, madeira clara, luz natural",
    "audience_notes": "casais montando o primeiro apartamento",
    "suggested_segment": None,
    "confidence": 0.6,
}

COPY_RESPONSE = {
    "caption": "Mais um projeto entregue!",
    "hashtags": ["marcenaria", "moveisplanejados"],
    "cta": "Fale com a gente!",
    "suggested_time": "18:00",
}

SLIDE_RESPONSE = {
    "title_card": {"headline": "5 erros ao contratar marcenaria", "subheadline": "Evite dor de cabeça"},
    "content_slides": [
        {"number": 1, "headline": "Erro 1", "body": "Não pedir referências"},
    ],
    "cta_card": {"headline": "Fale com a gente", "body": "Orçamento sem compromisso"},
}


# ─── Copywriter ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_copywriter_injects_scout_insights_when_present():
    """AC1 — com scout_insights presente, os 4 campos aparecem no prompt."""
    brand = {**BASE_BRAND, "scout_insights": SCOUT_INSIGHTS}
    captured = []

    async def capture(**kwargs):
        captured.append(kwargs)
        return _mock_claude_response(COPY_RESPONSE)

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = capture

        await generate_copy_with_ai(ANALYSIS, brand)

    user_msg = _content_to_str(captured[0]["messages"][0]["content"])
    assert "móveis planejados sob medida" in user_msg
    assert "cozinhas planejadas" in user_msg
    assert "ambientes finalizados, madeira clara, luz natural" in user_msg
    assert "casais montando o primeiro apartamento" in user_msg


@pytest.mark.asyncio
async def test_copywriter_no_scout_insights_no_regression():
    """AC3 — sem scout_insights, nenhum bloco do Scout aparece no prompt."""
    captured = []

    async def capture(**kwargs):
        captured.append(kwargs)
        return _mock_claude_response(COPY_RESPONSE)

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = capture

        await generate_copy_with_ai(ANALYSIS, BASE_BRAND)

    user_msg = _content_to_str(captured[0]["messages"][0]["content"])
    assert "PERFIL REAL DO CLIENTE" not in user_msg


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_insights", [
    {},
    {"recurring_topics": None},
    {"recurring_topics": "não é uma lista"},
    "nem um dict é",
    None,
])
async def test_copywriter_malformed_scout_insights_does_not_break(malformed_insights):
    """AC4 — scout_insights vazio/parcial/malformado nunca quebra a geração."""
    brand = {**BASE_BRAND, "scout_insights": malformed_insights}

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(COPY_RESPONSE))

        result = await generate_copy_with_ai(ANALYSIS, brand)

    assert "caption" in result


# ─── ThemeGenerator ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_theme_generator_injects_scout_insights_when_present():
    """AC2 (geração) — com scout_insights presente, contexto aparece no prompt."""
    brand = {**BASE_BRAND, "scout_insights": SCOUT_INSIGHTS}
    captured = []

    async def capture(**kwargs):
        captured.append(kwargs)
        return _mock_claude_response(SLIDE_RESPONSE)

    with patch("app.agents.theme_generator.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = capture

        await generate_slide_structure("cc_antes_assinar", brand)

    user_msg = captured[0]["messages"][0]["content"]
    assert "móveis planejados sob medida" in user_msg
    assert "cozinhas planejadas" in user_msg


@pytest.mark.asyncio
async def test_theme_generator_no_scout_insights_no_regression():
    """AC3 — sem scout_insights, prompt idêntico ao comportamento atual."""
    captured = []

    async def capture(**kwargs):
        captured.append(kwargs)
        return _mock_claude_response(SLIDE_RESPONSE)

    with patch("app.agents.theme_generator.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = capture

        await generate_slide_structure("cc_antes_assinar", BASE_BRAND)

    user_msg = captured[0]["messages"][0]["content"]
    assert "Considere esse contexto real" not in user_msg


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_insights", [{}, {"recurring_topics": 123}, "string solta", None])
async def test_theme_generator_malformed_scout_insights_does_not_break(malformed_insights):
    """AC4 — scout_insights malformado não quebra generate_slide_structure."""
    brand = {**BASE_BRAND, "scout_insights": malformed_insights}

    with patch("app.agents.theme_generator.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(SLIDE_RESPONSE))

        result = await generate_slide_structure("cc_antes_assinar", brand)

    assert "title_card" in result


# ─── Seleção de temas (app/api/insights.py) ──────────────────────

def test_theme_relevance_score_zero_without_recurring_topics():
    """AC3 — sem recurring_topics, relevância é sempre 0 (ordenação idêntica à atual)."""
    theme = {"id": "x", "tags": ["reforma", "dicas"]}
    assert _theme_relevance_score(theme, []) == 0


def test_theme_relevance_score_counts_tag_overlap():
    """AC2 (seleção) — tema com tags relacionadas a recurring_topics pontua mais."""
    theme_relevant = {"id": "cc_materiais_escolha", "tags": ["materiais", "comparativo", "revestimento"]}
    theme_irrelevant = {"id": "cc_tendencias_2026", "tags": ["tendencias", "acabamento", "2026"]}
    topics_normalized = ["materiais", "revestimento"]  # já normalizado (lowercase, sem acento)

    assert _theme_relevance_score(theme_relevant, topics_normalized) > \
        _theme_relevance_score(theme_irrelevant, topics_normalized)


def test_theme_relevance_score_handles_missing_tags():
    """AC4 — tema sem campo 'tags' não quebra o cálculo."""
    theme = {"id": "sem-tags"}
    assert _theme_relevance_score(theme, ["reforma"]) == 0
