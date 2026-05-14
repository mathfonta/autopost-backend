"""
Testes da Sequência de Ataque Editorial (Story 14.2).

Cobre:
- AC3: inject #OBJETIVO_SEQUENCIA no copywriter quando position < 10
- AC4: goals corretos por posição
- AC5: sem inject quando position >= 10
- AC6: incremento após publicação (via _increment_attack_sequence)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.copywriter import generate_copy_with_ai


# ─── Helpers ────────────────────────────────────────────────────

def _content_to_str(content) -> str:
    """Extrai texto de content list (prompt caching) ou string."""
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def _mock_claude(response_dict: dict):
    """Retorna (mock_cls, mock_client) já configurados para um call bem-sucedido."""
    mock_cls = MagicMock()
    mock_client = AsyncMock()
    mock_cls.return_value = mock_client

    message = MagicMock()
    message.content = [MagicMock()]
    message.content[0].text = json.dumps(response_dict)
    mock_client.messages.create = AsyncMock(return_value=message)
    return mock_cls, mock_client


ANALYSIS = {
    "quality": "good",
    "content_type": "obra_realizada",
    "description": "Projeto de acabamento.",
    "publish_clean": True,
}

BRAND = {
    "segment": "construção civil",
    "tone": "profissional",
    "city": "SP",
}

GOOD_RESPONSE = {
    "caption": "Post de teste.",
    "hashtags": ["construcao"],
    "cta": "Entre em contato.",
    "suggested_time": "18:00",
}


# ─── AC3/AC4 — inject #OBJETIVO_SEQUENCIA quando position < 10 ──

@pytest.mark.asyncio
@pytest.mark.parametrize("position,expected_goal", [
    (0, "Retenção — teste inicial"),
    (1, "Salvamentos"),
    (2, "Comentários e shares"),
    (3, "Qualificação de audiência"),
    (4, "Replays + permanência"),
    (5, "Consolidação"),
    (8, "Consolidação"),
    (9, "Consolidação"),
])
async def test_attack_section_injected_for_position(position, expected_goal):
    """AC3/AC4 — #OBJETIVO_SEQUENCIA injeta goal correto para cada posição."""
    mock_cls, mock_client = _mock_claude(GOOD_RESPONSE)
    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", mock_cls):
        await generate_copy_with_ai(
            analysis_result=ANALYSIS,
            brand_profile=BRAND,
            attack_sequence_position=position,
        )

    messages = mock_client.messages.create.call_args.kwargs["messages"]
    user_content = _content_to_str(messages[0]["content"])
    assert "#OBJETIVO_SEQUENCIA" in user_content, (
        f"position={position}: esperava #OBJETIVO_SEQUENCIA no prompt"
    )
    assert expected_goal in user_content, (
        f"position={position}: esperava '{expected_goal}' mas não encontrou"
    )


@pytest.mark.asyncio
async def test_attack_section_contains_post_number():
    """AC3 — prompt inclui número do post (ex: 'post 3/10')."""
    mock_cls, mock_client = _mock_claude(GOOD_RESPONSE)
    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", mock_cls):
        await generate_copy_with_ai(
            analysis_result=ANALYSIS,
            brand_profile=BRAND,
            attack_sequence_position=2,
        )

    messages = mock_client.messages.create.call_args.kwargs["messages"]
    user_content = _content_to_str(messages[0]["content"])
    assert "post 3/10" in user_content.lower()


# ─── AC5 — sem inject quando position >= 10 ─────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("position", [10, 11, 99])
async def test_no_attack_section_when_sequence_complete(position):
    """AC5 — #OBJETIVO_SEQUENCIA NÃO injeta quando position >= 10."""
    mock_cls, mock_client = _mock_claude(GOOD_RESPONSE)
    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", mock_cls):
        await generate_copy_with_ai(
            analysis_result=ANALYSIS,
            brand_profile=BRAND,
            attack_sequence_position=position,
        )

    messages = mock_client.messages.create.call_args.kwargs["messages"]
    user_content = _content_to_str(messages[0]["content"])
    assert "#OBJETIVO_SEQUENCIA" not in user_content, (
        f"position={position}: não deveria injetar #OBJETIVO_SEQUENCIA"
    )


@pytest.mark.asyncio
async def test_no_attack_section_when_position_none():
    """AC5 — sem #OBJETIVO_SEQUENCIA quando attack_sequence_position=None."""
    mock_cls, mock_client = _mock_claude(GOOD_RESPONSE)
    with patch("app.agents.copywriter.anthropic.AsyncAnthropic", mock_cls):
        await generate_copy_with_ai(
            analysis_result=ANALYSIS,
            brand_profile=BRAND,
            attack_sequence_position=None,
        )

    messages = mock_client.messages.create.call_args.kwargs["messages"]
    user_content = _content_to_str(messages[0]["content"])
    assert "#OBJETIVO_SEQUENCIA" not in user_content


# ─── AC6 — incremento de posição via _increment_attack_sequence ──

@pytest.mark.asyncio
async def test_increment_attack_sequence_increments_position():
    """AC6 — _increment_attack_sequence avança position de 0 para 1."""
    from app.tasks.pipeline import _increment_attack_sequence

    mock_client_obj = MagicMock()
    mock_client_obj.attack_sequence_position = 0

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_client_obj)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.database.WorkerSessionLocal", return_value=mock_session_ctx):
        await _increment_attack_sequence("00000000-0000-0000-0000-000000000001")

    assert mock_client_obj.attack_sequence_position == 1
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_increment_attack_sequence_caps_at_10():
    """AC6 — _increment_attack_sequence não ultrapassa 10."""
    from app.tasks.pipeline import _increment_attack_sequence

    mock_client_obj = MagicMock()
    mock_client_obj.attack_sequence_position = 10

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_client_obj)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.database.WorkerSessionLocal", return_value=mock_session_ctx):
        await _increment_attack_sequence("00000000-0000-0000-0000-000000000002")

    assert mock_client_obj.attack_sequence_position == 10
    mock_db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_increment_attack_sequence_noop_when_client_not_found():
    """AC6 — _increment_attack_sequence é silencioso quando client não existe."""
    from app.tasks.pipeline import _increment_attack_sequence

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.database.WorkerSessionLocal", return_value=mock_session_ctx):
        await _increment_attack_sequence("00000000-0000-0000-0000-000000000099")

    mock_db.commit.assert_not_called()
