"""
Testes do Agente Copywriter — mock do SDK Anthropic.
Não chama a API real.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.copywriter import generate_copy_with_ai, MAX_CAPTION_CHARS


# ─── Helpers ────────────────────────────────────────────────────

def _mock_claude_response(content: dict) -> MagicMock:
    message = MagicMock()
    message.content = [MagicMock()]
    message.content[0].text = json.dumps(content)
    return message


ANALYSIS = {
    "quality": "good",
    "content_type": "obra_realizada",
    "description": "Acabamento de piso em porcelanato cinza 90x90 em sala de estar.",
    "publish_clean": True,
    "stage": "acabamento",
}

BRAND = {
    "segment": "construção civil",
    "tone": "profissional",
    "city": "Florianópolis",
    "company_name": "Construtora Silva",
}

GOOD_RESPONSE = {
    "caption": "Mais um projeto entregue com excelência! ✨ Piso em porcelanato 90x90 que transforma qualquer ambiente.",
    "hashtags": ["construcaocivil", "porcelanato", "acabamento", "florianopolis", "reformas", "instagram", "brasil"],
    "cta": "Entre em contato pelo link na bio para um orçamento!",
    "suggested_time": "18:00",
}


# ─── Campos obrigatórios ────────────────────────────────────────


@pytest.mark.asyncio
async def test_returns_all_required_fields():
    """Deve retornar caption, hashtags, cta e suggested_time."""
    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(GOOD_RESPONSE))

        result = await generate_copy_with_ai(ANALYSIS, BRAND)

    assert "caption" in result
    assert "hashtags" in result
    assert "cta" in result
    assert "suggested_time" in result


@pytest.mark.asyncio
async def test_caption_within_instagram_limit():
    """Caption não deve ultrapassar 2200 chars."""
    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(GOOD_RESPONSE))

        result = await generate_copy_with_ai(ANALYSIS, BRAND)

    assert len(result["caption"]) <= MAX_CAPTION_CHARS


@pytest.mark.asyncio
async def test_caption_truncated_when_too_long():
    """Caption maior que 2200 chars deve ser truncada com reticências."""
    long_response = {**GOOD_RESPONSE, "caption": "A" * 3000}

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(long_response))

        result = await generate_copy_with_ai(ANALYSIS, BRAND)

    assert len(result["caption"]) <= MAX_CAPTION_CHARS
    assert result["caption"].endswith("...")


@pytest.mark.asyncio
async def test_hashtags_normalized():
    """Hashtags devem ser lowercase, sem # e sem espaços."""
    response = {**GOOD_RESPONSE, "hashtags": ["#Construção Civil", "#REFORMA", "porcelanato"]}

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(response))

        result = await generate_copy_with_ai(ANALYSIS, BRAND)

    for tag in result["hashtags"]:
        assert not tag.startswith("#")
        assert tag == tag.lower()
        assert " " not in tag


# ─── Tom de voz e contexto ──────────────────────────────────────


@pytest.mark.asyncio
async def test_brand_profile_sent_to_claude():
    """Segmento e cidade do brand_profile devem aparecer no prompt enviado."""
    captured = []

    async def capture(**kwargs):
        captured.append(kwargs)
        return _mock_claude_response(GOOD_RESPONSE)

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = capture

        await generate_copy_with_ai(ANALYSIS, BRAND)

    assert captured
    user_msg = captured[0]["messages"][0]["content"]
    assert "construção civil" in user_msg.lower()
    assert "florianópolis" in user_msg.lower() or "florianopolis" in user_msg.lower()


@pytest.mark.asyncio
async def test_analysis_description_sent_to_claude():
    """Descrição da foto deve aparecer no prompt enviado."""
    captured = []

    async def capture(**kwargs):
        captured.append(kwargs)
        return _mock_claude_response(GOOD_RESPONSE)

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = capture

        await generate_copy_with_ai(ANALYSIS, BRAND)

    user_msg = captured[0]["messages"][0]["content"]
    assert "porcelanato" in user_msg.lower()


# ─── Fallbacks e defaults ───────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_fields_get_defaults():
    """Campos ausentes na resposta devem receber defaults seguros."""
    minimal = {"caption": "Texto mínimo."}

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(minimal))

        result = await generate_copy_with_ai(ANALYSIS, BRAND)

    assert result["caption"] == "Texto mínimo."
    assert isinstance(result["hashtags"], list)
    assert result["cta"]
    assert result["suggested_time"]


@pytest.mark.asyncio
async def test_default_time_for_known_segment():
    """Segmento construção deve ter horário padrão 18:00 se Claude não sugerir."""
    minimal = {"caption": "Texto."}  # sem suggested_time

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(minimal))

        result = await generate_copy_with_ai(ANALYSIS, {"segment": "construção civil"})

    assert result["suggested_time"] == "18:00"


# ─── Robustez ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_json_raises_value_error():
    """Resposta não-JSON deve levantar ValueError."""
    message = MagicMock()
    message.content = [MagicMock()]
    message.content[0].text = "Desculpe, não consigo gerar a legenda agora."

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=message)

        with pytest.raises(ValueError, match="JSON inválido"):
            await generate_copy_with_ai(ANALYSIS, BRAND)


@pytest.mark.asyncio
async def test_timeout_propagates():
    """Timeout do Claude deve se propagar como exceção."""
    import anthropic as anthropic_lib

    with patch("app.agents.copywriter.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic_lib.APITimeoutError(request=MagicMock())
        )

        with pytest.raises(anthropic_lib.APITimeoutError):
            await generate_copy_with_ai(ANALYSIS, BRAND)
