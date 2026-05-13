"""
Testes de integração — Exa context no copywriter (Story 13.2)

Cenários cobertos:
- generate_copy_with_ai() com exa_context → injeta #TENDENCIAS_DO_NICHO no prompt
- generate_copy_with_ai() sem exa_context → backward compat, sem breaking change
- exa_context=None → nenhuma referência a TENDENCIAS no prompt
- Prompt contém o bloco Exa quando context presente
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ─── Fixtures ────────────────────────────────────────────────────────────────

ANALYSIS_RESULT = {
    "description": "Banheiro social com porcelanato branco 60x60cm",
    "content_type": "obra_realizada",
    "stage": "entregue",
    "quality": "good",
}

BRAND_PROFILE = {
    "segment": "Construção civil",
    "tone": "profissional",
    "city": "Florianópolis",
    "company_name": "Construtora Teste",
}

EXA_CONTEXT = (
    "[CONTEXTO DE MERCADO RECENTE]\n"
    "• Porcelanato grande formato domina menções em obras residenciais de alto padrão em 2025.\n"
    "• Vídeos antes e depois geram 4x mais saves que fotos estáticas."
)

MOCK_COPY_RESPONSE = {
    "caption_long": "Hook incrível.\n\nDesenvolvimento.\n\nCTA.",
    "caption_short": "Hook curto. CTA.",
    "caption_stories": "Stories.",
    "hashtags": ["construcaocivil", "porcelanato", "florianopolis"],
    "cta": "Me chama no DM 💬",
    "suggested_time": "18:00",
}


def _make_mock_claude_response(content: dict) -> MagicMock:
    import json
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(content))]
    return msg


# ─── Testes: parâmetro exa_context ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_copy_with_exa_context_injects_block():
    """Quando exa_context fornecido, o prompt deve conter #TENDENCIAS_DO_NICHO."""
    captured_prompt = {}

    async def fake_create(**kwargs):
        # Captura o user message para inspecionar
        msgs = kwargs.get("messages", [])
        if msgs:
            content_blocks = msgs[0].get("content", [])
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    captured_prompt["user_msg"] = block.get("text", "")
        return _make_mock_claude_response(MOCK_COPY_RESPONSE)

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with (
        patch("app.agents.copywriter.get_settings") as mock_settings,
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
        patch("app.cerebro.reader.read_patterns", return_value=""),
    ):
        mock_settings.return_value.COPY_PROVIDER = "claude"
        mock_settings.return_value.ANTHROPIC_API_KEY = "sk-test"

        from app.agents.copywriter import generate_copy_with_ai
        result = await generate_copy_with_ai(
            ANALYSIS_RESULT,
            BRAND_PROFILE,
            exa_context=EXA_CONTEXT,
        )

    assert result is not None
    assert "caption_long" in result
    # O user_message deve conter o bloco Exa
    user_msg = captured_prompt.get("user_msg", "")
    assert "#TENDENCIAS_DO_NICHO" in user_msg
    assert "Porcelanato grande formato" in user_msg


@pytest.mark.asyncio
async def test_generate_copy_without_exa_context_no_tendencias_block():
    """Sem exa_context, o prompt NÃO deve conter #TENDENCIAS_DO_NICHO."""
    captured_prompt = {}

    async def fake_create(**kwargs):
        msgs = kwargs.get("messages", [])
        if msgs:
            content_blocks = msgs[0].get("content", [])
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    captured_prompt["user_msg"] = block.get("text", "")
        return _make_mock_claude_response(MOCK_COPY_RESPONSE)

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with (
        patch("app.agents.copywriter.get_settings") as mock_settings,
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
        patch("app.cerebro.reader.read_patterns", return_value=""),
    ):
        mock_settings.return_value.COPY_PROVIDER = "claude"
        mock_settings.return_value.ANTHROPIC_API_KEY = "sk-test"

        from app.agents.copywriter import generate_copy_with_ai
        result = await generate_copy_with_ai(
            ANALYSIS_RESULT,
            BRAND_PROFILE,
            exa_context=None,
        )

    assert result is not None
    user_msg = captured_prompt.get("user_msg", "")
    assert "#TENDENCIAS_DO_NICHO" not in user_msg


@pytest.mark.asyncio
async def test_generate_copy_exa_none_backward_compat():
    """exa_context default=None — backward compatible, não quebra calls existentes."""

    async def fake_create(**kwargs):
        return _make_mock_claude_response(MOCK_COPY_RESPONSE)

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with (
        patch("app.agents.copywriter.get_settings") as mock_settings,
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
        patch("app.cerebro.reader.read_patterns", return_value=""),
    ):
        mock_settings.return_value.COPY_PROVIDER = "claude"
        mock_settings.return_value.ANTHROPIC_API_KEY = "sk-test"

        from app.agents.copywriter import generate_copy_with_ai
        # Chamada sem exa_context — signature antiga
        result = await generate_copy_with_ai(
            ANALYSIS_RESULT,
            BRAND_PROFILE,
        )

    assert result is not None
    assert result["caption_long"] == MOCK_COPY_RESPONSE["caption_long"]


@pytest.mark.asyncio
async def test_generate_copy_with_gemini_and_exa_context():
    """exa_context funciona também com provider Gemini."""
    captured_prompt = {}

    async def fake_gemini(prompt: str):
        import json
        captured_prompt["full"] = prompt
        return json.dumps(MOCK_COPY_RESPONSE)

    with (
        patch("app.agents.copywriter.get_settings") as mock_settings,
        patch("app.agents.copywriter._call_gemini_for_copy", side_effect=fake_gemini),
        patch("app.cerebro.reader.read_patterns", return_value=""),
    ):
        mock_settings.return_value.COPY_PROVIDER = "gemini"
        mock_settings.return_value.ANTHROPIC_API_KEY = "sk-test"

        from app.agents.copywriter import generate_copy_with_ai
        result = await generate_copy_with_ai(
            ANALYSIS_RESULT,
            BRAND_PROFILE,
            exa_context=EXA_CONTEXT,
        )

    assert result is not None
    # O user_message passado ao Gemini deve conter o bloco Exa
    assert "#TENDENCIAS_DO_NICHO" in captured_prompt.get("full", "")


# ─── Testes: exa_context vazio ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_copy_with_empty_exa_context():
    """exa_context string vazia → mesmo comportamento que None."""
    captured_prompt = {}

    async def fake_create(**kwargs):
        msgs = kwargs.get("messages", [])
        if msgs:
            content_blocks = msgs[0].get("content", [])
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    captured_prompt["user_msg"] = block.get("text", "")
        return _make_mock_claude_response(MOCK_COPY_RESPONSE)

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=fake_create)

    with (
        patch("app.agents.copywriter.get_settings") as mock_settings,
        patch("anthropic.AsyncAnthropic", return_value=mock_client),
        patch("app.cerebro.reader.read_patterns", return_value=""),
    ):
        mock_settings.return_value.COPY_PROVIDER = "claude"
        mock_settings.return_value.ANTHROPIC_API_KEY = "sk-test"

        from app.agents.copywriter import generate_copy_with_ai
        result = await generate_copy_with_ai(
            ANALYSIS_RESULT,
            BRAND_PROFILE,
            exa_context="",  # string vazia
        )

    assert result is not None
    user_msg = captured_prompt.get("user_msg", "")
    assert "#TENDENCIAS_DO_NICHO" not in user_msg
