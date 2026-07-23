"""
Testes unitários para app/tools/instagram_media.py (Story 22.1).

Cenários cobertos (AC7):
- fetch_recent_media: caminho feliz (N posts)
- fetch_recent_media: conta vazia ([])
- fetch_recent_media: erro #190 (token expirado/inválido) → [] + log
- fetch_recent_media: resposta malformada → [] + log
- fetch_recent_media: falha de rede → [] (AC4)
- fetch_account_info: caminho feliz
- fetch_account_info: falha → None
"""

import httpx
import pytest
import respx

from app.tools.instagram_media import fetch_account_info, fetch_recent_media

IG_ID = "ig-scout-999"
TOKEN = "long-token-scout"

MOCK_MEDIA_RESPONSE = {
    "data": [
        {
            "id": "media-1",
            "caption": "Reforma finalizada em cozinha planejada",
            "media_type": "IMAGE",
            "media_url": "https://cdn.example.com/media-1.jpg",
            "thumbnail_url": None,
            "permalink": "https://instagram.com/p/media-1",
            "timestamp": "2026-07-01T10:00:00+0000",
            "like_count": 42,
            "comments_count": 3,
        },
        {
            "id": "media-2",
            "caption": "Antes e depois de um projeto de marcenaria",
            "media_type": "VIDEO",
            "media_url": "https://cdn.example.com/media-2.mp4",
            "thumbnail_url": "https://cdn.example.com/media-2-thumb.jpg",
            "permalink": "https://instagram.com/p/media-2",
            "timestamp": "2026-06-15T14:30:00+0000",
            "like_count": 108,
            "comments_count": 12,
        },
    ]
}

MOCK_ACCOUNT_RESPONSE = {
    "username": "marcenaria_silva",
    "biography": "Móveis planejados sob medida | Orçamento sem compromisso",
    "followers_count": 3200,
    "media_count": 87,
    "profile_picture_url": "https://cdn.example.com/profile.jpg",
}


# ─── fetch_recent_media ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_recent_media_success():
    """Caminho feliz: retorna a lista de posts com todos os campos esperados."""
    with respx.mock:
        respx.get(f"https://graph.instagram.com/{IG_ID}/media").mock(
            return_value=httpx.Response(200, json=MOCK_MEDIA_RESPONSE)
        )
        result = await fetch_recent_media(IG_ID, TOKEN, limit=12)

    assert len(result) == 2
    assert result[0]["id"] == "media-1"
    assert result[1]["media_type"] == "VIDEO"
    assert result[1]["thumbnail_url"] == "https://cdn.example.com/media-2-thumb.jpg"


@pytest.mark.asyncio
async def test_fetch_recent_media_empty_account():
    """Conta sem posts retorna [] — não é erro."""
    with respx.mock:
        respx.get(f"https://graph.instagram.com/{IG_ID}/media").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        result = await fetch_recent_media(IG_ID, TOKEN)

    assert result == []


@pytest.mark.asyncio
async def test_fetch_recent_media_token_error_190():
    """Erro #190 (token expirado/inválido) retorna [] sem levantar exceção."""
    with respx.mock:
        respx.get(f"https://graph.instagram.com/{IG_ID}/media").mock(
            return_value=httpx.Response(
                400, json={"error": {"message": "Token inválido", "code": 190}}
            )
        )
        result = await fetch_recent_media(IG_ID, TOKEN)

    assert result == []


@pytest.mark.asyncio
async def test_fetch_recent_media_malformed_response():
    """Resposta malformada (campo 'data' não é lista) retorna [] sem quebrar."""
    with respx.mock:
        respx.get(f"https://graph.instagram.com/{IG_ID}/media").mock(
            return_value=httpx.Response(200, json={"data": "not-a-list"})
        )
        result = await fetch_recent_media(IG_ID, TOKEN)

    assert result == []


@pytest.mark.asyncio
async def test_fetch_recent_media_network_failure():
    """Falha de rede (timeout/conexão) retorna [] sem levantar exceção (AC4)."""
    with respx.mock:
        respx.get(f"https://graph.instagram.com/{IG_ID}/media").mock(
            side_effect=httpx.ConnectTimeout("timeout simulado")
        )
        result = await fetch_recent_media(IG_ID, TOKEN)

    assert result == []


@pytest.mark.asyncio
async def test_fetch_recent_media_missing_credentials():
    """ig_id ou access_token ausentes retornam [] sem chamar a API."""
    result_no_token = await fetch_recent_media(IG_ID, "")
    result_no_id = await fetch_recent_media("", TOKEN)

    assert result_no_token == []
    assert result_no_id == []


@pytest.mark.asyncio
async def test_fetch_recent_media_requests_correct_fields_and_limit():
    """Garante que 'fields' (AC2) e 'limit' (AC5) são de fato enviados na requisição —
    não só que a função retorna certo quando a API já responde certo."""
    with respx.mock:
        route = respx.get(f"https://graph.instagram.com/{IG_ID}/media").mock(
            return_value=httpx.Response(200, json=MOCK_MEDIA_RESPONSE)
        )
        await fetch_recent_media(IG_ID, TOKEN, limit=7)

    sent_params = route.calls.last.request.url.params
    assert sent_params["limit"] == "7"
    for field in (
        "id", "caption", "media_type", "media_url", "thumbnail_url",
        "permalink", "timestamp", "like_count", "comments_count",
    ):
        assert field in sent_params["fields"]


# ─── fetch_account_info ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_account_info_success():
    """Caminho feliz: retorna dict com bio, username, seguidores etc."""
    with respx.mock:
        respx.get(f"https://graph.instagram.com/{IG_ID}").mock(
            return_value=httpx.Response(200, json=MOCK_ACCOUNT_RESPONSE)
        )
        result = await fetch_account_info(IG_ID, TOKEN)

    assert result is not None
    assert result["username"] == "marcenaria_silva"
    assert "Móveis planejados" in result["biography"]
    assert result["followers_count"] == 3200


@pytest.mark.asyncio
async def test_fetch_account_info_failure_returns_none():
    """Falha na API (ex.: token inválido) retorna None sem levantar exceção."""
    with respx.mock:
        respx.get(f"https://graph.instagram.com/{IG_ID}").mock(
            return_value=httpx.Response(
                400, json={"error": {"message": "Token inválido", "code": 190}}
            )
        )
        result = await fetch_account_info(IG_ID, TOKEN)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_account_info_requests_correct_fields():
    """Garante que os 5 campos de conta/bio (AC6) são de fato solicitados na requisição."""
    with respx.mock:
        route = respx.get(f"https://graph.instagram.com/{IG_ID}").mock(
            return_value=httpx.Response(200, json=MOCK_ACCOUNT_RESPONSE)
        )
        await fetch_account_info(IG_ID, TOKEN)

    sent_params = route.calls.last.request.url.params
    for field in (
        "username", "biography", "followers_count", "media_count", "profile_picture_url",
    ):
        assert field in sent_params["fields"]
