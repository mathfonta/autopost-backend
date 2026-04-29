"""
Testes da Skill Library do Copywriter — Story 9.2.
Verifica que a instrução correta é injetada no user_message por estratégia.
Não chama a API real.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.copywriter import generate_copy_with_ai, STRATEGY_PROMPTS


# ─── Helpers ────────────────────────────────────────────────────

def _mock_claude_response() -> MagicMock:
    message = MagicMock()
    message.content = [MagicMock()]
    message.content[0].text = json.dumps({
        "caption_long":    "Legenda longa gerada",
        "caption_short":   "Legenda curta",
        "caption_stories": "Stories",
        "hashtags":        ["teste", "instagram"],
        "cta":             "Entre em contato!",
        "suggested_time":  "19:00",
    })
    return message


ANALYSIS = {
    "quality": "good",
    "content_type": "obra_realizada",
    "description": "Sala de estar reformada com piso novo.",
    "publish_clean": True,
    "stage": "acabamento",
}

BRAND = {
    "segment": "construção civil",
    "tone":    "profissional",
    "city":    "Florianópolis",
    "company_name": "Construção Teste",
}


# ─── Testes de cobertura da Skill Library ───────────────────────

def test_strategy_prompts_count():
    """Skill Library deve ter exatamente 23 entradas."""
    assert len(STRATEGY_PROMPTS) == 23


def test_strategy_prompts_feed_photo():
    """Feed Photo deve ter 5 sub-estratégias."""
    feed_keys = [k for k in STRATEGY_PROMPTS if k.startswith("feed_photo__")]
    assert len(feed_keys) == 5


def test_strategy_prompts_carousel():
    """Carousel deve ter 6 sub-estratégias."""
    keys = [k for k in STRATEGY_PROMPTS if k.startswith("carousel__")]
    assert len(keys) == 6


def test_strategy_prompts_reels():
    """Reels deve ter 6 sub-estratégias."""
    keys = [k for k in STRATEGY_PROMPTS if k.startswith("reels__")]
    assert len(keys) == 6


def test_strategy_prompts_story():
    """Story deve ter 6 sub-estratégias."""
    keys = [k for k in STRATEGY_PROMPTS if k.startswith("story__")]
    assert len(keys) == 6


def test_all_strategy_prompts_non_empty():
    """Todas as entradas da Skill Library devem ter texto não vazio."""
    for key, value in STRATEGY_PROMPTS.items():
        assert value.strip(), f"STRATEGY_PROMPTS['{key}'] está vazio"


# ─── Testes de injeção no user_message ──────────────────────────

@pytest.mark.asyncio
async def test_strategy_injected_in_message():
    """Quando strategy fornecida, instrução correta deve aparecer no user_message."""
    captured_messages = []

    async def mock_create(**kwargs):
        captured_messages.append(kwargs["messages"][0]["content"])
        return _mock_claude_response()

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", return_value=mock_client), \
         patch("app.agents.copywriter.read_patterns", return_value=""):
        await generate_copy_with_ai(
            ANALYSIS, BRAND,
            user_content_type="feed_photo",
            strategy="prova_social",
        )

    assert captured_messages, "Nenhuma mensagem capturada"
    user_msg = captured_messages[0]
    assert "ESTRATÉGIA" in user_msg
    assert "Prova Social" in user_msg


@pytest.mark.asyncio
async def test_strategy_none_no_injection():
    """Sem strategy, user_message não deve conter bloco ESTRATÉGIA."""
    captured_messages = []

    async def mock_create(**kwargs):
        captured_messages.append(kwargs["messages"][0]["content"])
        return _mock_claude_response()

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", return_value=mock_client), \
         patch("app.agents.copywriter.read_patterns", return_value=""):
        await generate_copy_with_ai(
            ANALYSIS, BRAND,
            user_content_type="post_simples",
            strategy=None,
        )

    user_msg = captured_messages[0]
    assert "ESTRATÉGIA:" not in user_msg


@pytest.mark.asyncio
async def test_strategy_unknown_key_no_crash():
    """Strategy com chave desconhecida não deve crashar — usa fallback silencioso."""
    async def mock_create(**kwargs):
        return _mock_claude_response()

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", return_value=mock_client), \
         patch("app.agents.copywriter.read_patterns", return_value=""):
        result = await generate_copy_with_ai(
            ANALYSIS, BRAND,
            user_content_type="feed_photo",
            strategy="estrategia_inexistente",
        )

    assert "caption_long" in result


@pytest.mark.asyncio
async def test_carousel_antes_depois_strategy():
    """Carrossel + Antes & Depois deve injetar instrução de transformação."""
    captured_messages = []

    async def mock_create(**kwargs):
        captured_messages.append(kwargs["messages"][0]["content"])
        return _mock_claude_response()

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", return_value=mock_client), \
         patch("app.agents.copywriter.read_patterns", return_value=""):
        await generate_copy_with_ai(
            ANALYSIS, BRAND,
            user_content_type="carousel",
            strategy="antes_depois",
        )

    user_msg = captured_messages[0]
    assert "transformação" in user_msg.lower() or "Antes & Depois" in user_msg


@pytest.mark.asyncio
async def test_reels_hook_choque_strategy():
    """Reels + Hook de Choque deve injetar instrução de 3 segundos."""
    captured_messages = []

    async def mock_create(**kwargs):
        captured_messages.append(kwargs["messages"][0]["content"])
        return _mock_claude_response()

    mock_client = MagicMock()
    mock_client.messages.create = mock_create

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", return_value=mock_client), \
         patch("app.agents.copywriter.read_patterns", return_value=""):
        await generate_copy_with_ai(
            ANALYSIS, BRAND,
            user_content_type="reels",
            strategy="hook_choque",
        )

    user_msg = captured_messages[0]
    assert "Hook" in user_msg or "choque" in user_msg.lower()
