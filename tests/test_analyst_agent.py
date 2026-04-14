"""
Testes do Agente Analista de Foto — mock do SDK Anthropic.
Não chama a API real.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.analyst import analyze_photo_with_ai, _QUALITY_MESSAGES


# ─── Helpers ────────────────────────────────────────────────────

def _mock_claude_response(content: dict) -> MagicMock:
    """Cria um mock da resposta do SDK Anthropic."""
    message = MagicMock()
    message.content = [MagicMock()]
    message.content[0].text = json.dumps(content)
    return message


PHOTO_URL = "https://r2.example.com/test/photo.jpg"
BRAND_PROFILE = {"segment": "construção civil", "city": "Florianópolis", "tone": "profissional"}


# ─── Análise de qualidade ────────────────────────────────────────


@pytest.mark.asyncio
async def test_good_photo_returns_correct_fields():
    """Foto boa deve retornar todos os campos obrigatórios."""
    response_data = {
        "quality": "good",
        "quality_reason": "ok",
        "content_type": "obra_realizada",
        "description": "Acabamento de piso em porcelanato.",
        "publish_clean": True,
        "stage": "acabamento",
    }

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(response_data))

        result = await analyze_photo_with_ai(PHOTO_URL, BRAND_PROFILE)

    assert result["quality"] == "good"
    assert result["content_type"] == "obra_realizada"
    assert result["publish_clean"] is True
    assert "description" in result
    assert "error_message" not in result


@pytest.mark.asyncio
async def test_bad_photo_adds_error_message():
    """Foto ruim deve incluir error_message amigável."""
    response_data = {
        "quality": "bad",
        "quality_reason": "dark",
        "content_type": "obra_realizada",
        "description": "Foto muito escura, impossível identificar o conteúdo.",
        "publish_clean": True,
        "stage": "",
    }

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(response_data))

        result = await analyze_photo_with_ai(PHOTO_URL, BRAND_PROFILE)

    assert result["quality"] == "bad"
    assert "error_message" in result
    assert "luz" in result["error_message"].lower()  # mensagem sobre luz para foto escura


@pytest.mark.asyncio
async def test_bad_photo_blurry_message():
    """Foto borrada deve ter mensagem específica de foco."""
    response_data = {
        "quality": "bad",
        "quality_reason": "blurry",
        "content_type": "outro",
        "description": "Imagem fora de foco.",
        "publish_clean": False,
        "stage": "",
    }

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(response_data))

        result = await analyze_photo_with_ai(PHOTO_URL, BRAND_PROFILE)

    assert result["quality"] == "bad"
    assert "foco" in result["error_message"].lower()


@pytest.mark.asyncio
async def test_acceptable_photo_no_error_message():
    """Foto aceitável não deve ter error_message."""
    response_data = {
        "quality": "acceptable",
        "quality_reason": "ok",
        "content_type": "obra_realizada",
        "description": "Foto de obra com iluminação média.",
        "publish_clean": True,
        "stage": "estrutura",
    }

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(response_data))

        result = await analyze_photo_with_ai(PHOTO_URL, BRAND_PROFILE)

    assert result["quality"] == "acceptable"
    assert "error_message" not in result


# ─── Tipos de conteúdo ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_antes_depois_publish_clean_false():
    """Antes/depois pode ter publish_clean=False dependendo da análise."""
    response_data = {
        "quality": "good",
        "quality_reason": "ok",
        "content_type": "antes_depois",
        "description": "Comparação antes e depois de reforma.",
        "publish_clean": False,
        "stage": "reforma concluída",
    }

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(response_data))

        result = await analyze_photo_with_ai(PHOTO_URL, BRAND_PROFILE)

    assert result["content_type"] == "antes_depois"
    assert result["publish_clean"] is False


# ─── Robustez / erros ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_json_raises_value_error():
    """Resposta não-JSON do Claude deve levantar ValueError."""
    message = MagicMock()
    message.content = [MagicMock()]
    message.content[0].text = "Desculpe, não consigo analisar esta imagem."

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=message)

        with pytest.raises(ValueError, match="JSON inválido"):
            await analyze_photo_with_ai(PHOTO_URL, BRAND_PROFILE)


@pytest.mark.asyncio
async def test_missing_fields_get_defaults():
    """Campos ausentes na resposta do Claude devem receber defaults."""
    # Resposta mínima sem todos os campos
    response_data = {"quality": "good"}

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(response_data))

        result = await analyze_photo_with_ai(PHOTO_URL, BRAND_PROFILE)

    assert result["quality"] == "good"
    assert "content_type" in result
    assert "publish_clean" in result
    assert "description" in result


@pytest.mark.asyncio
async def test_uses_brand_profile_in_context():
    """O brand_profile deve ser usado para construir o contexto enviado ao Claude."""
    response_data = {
        "quality": "good",
        "quality_reason": "ok",
        "content_type": "obra_realizada",
        "description": "Teste.",
        "publish_clean": True,
        "stage": "",
    }
    captured_messages = []

    async def capture_create(**kwargs):
        captured_messages.append(kwargs)
        return _mock_claude_response(response_data)

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = capture_create

        await analyze_photo_with_ai(PHOTO_URL, {"segment": "arquitetura", "city": "São Paulo"})

    assert captured_messages
    user_text = captured_messages[0]["messages"][0]["content"][1]["text"]
    assert "arquitetura" in user_text.lower()
    assert "são paulo" in user_text.lower()


@pytest.mark.asyncio
async def test_timeout_propagates():
    """Timeout do Claude deve se propagar como exceção."""
    import anthropic as anthropic_lib

    with patch("app.agents.analyst.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic_lib.APITimeoutError(request=MagicMock())
        )

        with pytest.raises(anthropic_lib.APITimeoutError):
            await analyze_photo_with_ai(PHOTO_URL, BRAND_PROFILE)
