"""
Testes do Agente Onboarding + endpoints.
Não chama API Anthropic nem Redis real.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.onboarding import (
    start_session,
    process_message,
    get_session,
    _extract_profile,
    _OPENING_MESSAGE,
)


# ─── Helpers ────────────────────────────────────────────────────

CLIENT_ID = "client-uuid-123"

COMPLETE_RESPONSE = (
    "Perfeito! Seu perfil está pronto.\n\n"
    "PROFILE_COMPLETE\n"
    '{"company_name": "Construtora Silva", "segment": "construção civil", '
    '"city": "Florianópolis", "tone": "profissional", '
    '"primary_color": "#1A3C6E", "has_instagram": true}'
)

PARTIAL_RESPONSE = "Entendido! Qual é a cidade onde você atua?"


# ─── _extract_profile ───────────────────────────────────────────

def test_extract_profile_from_complete_response():
    """Deve extrair brand_profile quando PROFILE_COMPLETE está presente."""
    profile = _extract_profile(COMPLETE_RESPONSE)
    assert profile is not None
    assert profile["company_name"] == "Construtora Silva"
    assert profile["segment"] == "construção civil"
    assert profile["city"] == "Florianópolis"
    assert profile["tone"] == "profissional"


def test_extract_profile_returns_none_without_marker():
    """Sem PROFILE_COMPLETE, deve retornar None."""
    result = _extract_profile(PARTIAL_RESPONSE)
    assert result is None


def test_extract_profile_handles_invalid_json():
    """JSON malformado após PROFILE_COMPLETE deve retornar None."""
    bad = "PROFILE_COMPLETE\n{invalid json here"
    result = _extract_profile(bad)
    assert result is None


# ─── start_session ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_session_returns_opening_message():
    """start_session deve retornar a mensagem de boas-vindas."""
    with patch("app.agents.onboarding.save_session", new_callable=AsyncMock):
        result = await start_session(CLIENT_ID)

    assert result["done"] is False
    assert "AutoPost" in result["last_message"]
    assert result["last_message"] == _OPENING_MESSAGE


@pytest.mark.asyncio
async def test_start_session_saves_to_redis():
    """start_session deve chamar save_session."""
    saved = []

    async def fake_save(client_id, session):
        saved.append((client_id, session))

    with patch("app.agents.onboarding.save_session", side_effect=fake_save):
        await start_session(CLIENT_ID)

    assert saved
    assert saved[0][0] == CLIENT_ID
    session = saved[0][1]
    assert len(session["messages"]) == 1
    assert session["messages"][0]["role"] == "assistant"


# ─── process_message ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_message_returns_claude_reply():
    """Deve retornar a resposta do Claude com done=False."""
    existing_session = {"messages": [{"role": "assistant", "content": _OPENING_MESSAGE}], "done": False, "brand_profile": None}

    with (
        patch("app.agents.onboarding.get_session", return_value=existing_session),
        patch("app.agents.onboarding.save_session", new_callable=AsyncMock),
        patch("app.agents.onboarding._call_claude", return_value=PARTIAL_RESPONSE),
    ):
        result = await process_message(CLIENT_ID, "Construtora Silva")

    assert result["reply"] == PARTIAL_RESPONSE
    assert result["done"] is False
    assert result["brand_profile"] is None


@pytest.mark.asyncio
async def test_process_message_detects_completion():
    """Quando Claude emite PROFILE_COMPLETE, done deve ser True."""
    existing_session = {
        "messages": [{"role": "assistant", "content": _OPENING_MESSAGE}],
        "done": False,
        "brand_profile": None,
    }

    with (
        patch("app.agents.onboarding.get_session", return_value=existing_session),
        patch("app.agents.onboarding.save_session", new_callable=AsyncMock),
        patch("app.agents.onboarding._call_claude", return_value=COMPLETE_RESPONSE),
    ):
        result = await process_message(CLIENT_ID, "sim, está certo!")

    assert result["done"] is True
    assert result["brand_profile"] is not None
    assert result["brand_profile"]["segment"] == "construção civil"
    # Marcador técnico não deve aparecer na reply exibida ao usuário
    assert "PROFILE_COMPLETE" not in result["reply"]


@pytest.mark.asyncio
async def test_process_message_profile_complete_cleans_reply():
    """O marcador PROFILE_COMPLETE deve ser removido da resposta final."""
    existing_session = {"messages": [], "done": False, "brand_profile": None}

    with (
        patch("app.agents.onboarding.get_session", return_value=existing_session),
        patch("app.agents.onboarding.save_session", new_callable=AsyncMock),
        patch("app.agents.onboarding._call_claude", return_value=COMPLETE_RESPONSE),
    ):
        result = await process_message(CLIENT_ID, "sim")

    assert "PROFILE_COMPLETE" not in result["reply"]
    assert "{" not in result["reply"]


@pytest.mark.asyncio
async def test_process_message_already_done():
    """Se sessão já está concluída, deve retornar mensagem informativa."""
    done_session = {
        "messages": [],
        "done": True,
        "brand_profile": {"company_name": "Construtora Silva", "segment": "construção civil"},
    }

    with patch("app.agents.onboarding.get_session", return_value=done_session):
        result = await process_message(CLIENT_ID, "oi")

    assert result["done"] is True
    assert result["brand_profile"] is not None


@pytest.mark.asyncio
async def test_process_message_expired_session_restarts():
    """Sessão expirada (None) deve reiniciar automaticamente."""
    with (
        patch("app.agents.onboarding.get_session", return_value=None),
        patch("app.agents.onboarding.save_session", new_callable=AsyncMock),
        patch("app.agents.onboarding._call_claude", return_value=PARTIAL_RESPONSE),
    ):
        result = await process_message(CLIENT_ID, "olá")

    assert result["done"] is False


@pytest.mark.asyncio
async def test_process_message_appends_to_history():
    """Histórico de mensagens deve crescer a cada interação."""
    existing_session = {
        "messages": [{"role": "assistant", "content": _OPENING_MESSAGE}],
        "done": False,
        "brand_profile": None,
    }
    saved_sessions = []

    async def fake_save(client_id, session):
        saved_sessions.append(session)

    with (
        patch("app.agents.onboarding.get_session", return_value=existing_session),
        patch("app.agents.onboarding.save_session", side_effect=fake_save),
        patch("app.agents.onboarding._call_claude", return_value=PARTIAL_RESPONSE),
    ):
        await process_message(CLIENT_ID, "Construtora Silva")

    # 1 assistente inicial + 1 user + 1 assistente = 3
    assert len(saved_sessions[-1]["messages"]) == 3


# ─── get_session ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_session_returns_none_when_not_found():
    """get_session deve retornar None se não existir no Redis."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with patch("app.agents.onboarding.get_redis", return_value=mock_redis):
        result = await get_session("nonexistent-id")

    assert result is None


@pytest.mark.asyncio
async def test_get_session_deserializes_json():
    """get_session deve desserializar o JSON do Redis."""
    session_data = {"messages": [], "done": False, "brand_profile": None}
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(session_data))

    with patch("app.agents.onboarding.get_redis", return_value=mock_redis):
        result = await get_session(CLIENT_ID)

    assert result == session_data
