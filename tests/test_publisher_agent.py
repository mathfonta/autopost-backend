"""
Testes do Agente Publicador — mock da Meta Graph API via respx.
Não faz chamadas reais à API.
"""

import pytest
import respx
from httpx import Response

from app.agents.publisher import (
    publish_to_instagram,
    publish_to_facebook,
    collect_post_metrics,
    build_full_caption,
    MetaAPIError,
    GRAPH_BASE,
)

IG_ID = "123456789"
FB_ID = "987654321"
TOKEN = "test-access-token"
IMAGE_URL = "https://pub.r2.dev/processed/test/final.jpg"
CAPTION = "Legenda do post.\n\nEntre em contato!\n\n#construcaocivil"


# ─── build_full_caption ─────────────────────────────────────────

def test_build_full_caption_combines_fields():
    copy = {
        "caption": "Mais um projeto entregue! ✨",
        "cta": "Entre em contato pelo link na bio!",
        "hashtags": ["construcaocivil", "porcelanato", "florianopolis"],
    }
    result = build_full_caption(copy)
    assert "Mais um projeto" in result
    assert "Entre em contato" in result
    assert "#construcaocivil" in result
    assert result.count("\n\n") == 2  # 3 partes separadas


def test_build_full_caption_empty_hashtags():
    copy = {"caption": "Texto.", "cta": "CTA.", "hashtags": []}
    result = build_full_caption(copy)
    assert result == "Texto.\n\nCTA."


# ─── publish_to_instagram ───────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_instagram_two_step_publish():
    """publish_to_instagram deve criar container e publicar (2 POSTs + 1 GET)."""
    respx.post(f"{GRAPH_BASE}/{IG_ID}/media").mock(
        return_value=Response(200, json={"id": "container-id-abc"})
    )
    respx.post(f"{GRAPH_BASE}/{IG_ID}/media_publish").mock(
        return_value=Response(200, json={"id": "post-id-xyz"})
    )
    respx.get(f"{GRAPH_BASE}/post-id-xyz").mock(
        return_value=Response(200, json={"id": "post-id-xyz", "permalink": "https://www.instagram.com/p/abc123/"})
    )

    result = await publish_to_instagram(IG_ID, TOKEN, IMAGE_URL, CAPTION)

    assert result["post_id"] == "post-id-xyz"
    assert result["permalink"] == "https://www.instagram.com/p/abc123/"


@pytest.mark.asyncio
@respx.mock
async def test_instagram_returns_post_id_and_permalink():
    """Resultado deve conter post_id e permalink."""
    respx.post(f"{GRAPH_BASE}/{IG_ID}/media").mock(
        return_value=Response(200, json={"id": "c1"})
    )
    respx.post(f"{GRAPH_BASE}/{IG_ID}/media_publish").mock(
        return_value=Response(200, json={"id": "p1"})
    )
    respx.get(f"{GRAPH_BASE}/p1").mock(
        return_value=Response(200, json={"permalink": "https://www.instagram.com/p/p1/"})
    )

    result = await publish_to_instagram(IG_ID, TOKEN, IMAGE_URL, CAPTION)

    assert "post_id" in result
    assert "permalink" in result


@pytest.mark.asyncio
@respx.mock
async def test_instagram_token_expired_raises_meta_error():
    """Error code 190 deve levantar MetaAPIError com is_token_expired=True."""
    respx.post(f"{GRAPH_BASE}/{IG_ID}/media").mock(
        return_value=Response(200, json={
            "error": {"code": 190, "message": "Invalid OAuth access token"}
        })
    )

    with pytest.raises(MetaAPIError) as exc_info:
        await publish_to_instagram(IG_ID, TOKEN, IMAGE_URL, CAPTION)

    assert exc_info.value.is_token_expired is True
    assert exc_info.value.code == 190


@pytest.mark.asyncio
@respx.mock
async def test_instagram_api_error_raises_meta_error():
    """Qualquer erro da API deve levantar MetaAPIError."""
    respx.post(f"{GRAPH_BASE}/{IG_ID}/media").mock(
        return_value=Response(200, json={
            "error": {"code": 100, "message": "Invalid parameter"}
        })
    )

    with pytest.raises(MetaAPIError) as exc_info:
        await publish_to_instagram(IG_ID, TOKEN, IMAGE_URL, CAPTION)

    assert exc_info.value.is_token_expired is False


# ─── publish_to_facebook ────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_facebook_publish_returns_post_id():
    """publish_to_facebook deve retornar post_id."""
    respx.post(f"{GRAPH_BASE}/{FB_ID}/photos").mock(
        return_value=Response(200, json={"post_id": "fb-post-123", "id": "photo-id"})
    )

    result = await publish_to_facebook(FB_ID, TOKEN, IMAGE_URL, CAPTION)

    assert result["post_id"] == "fb-post-123"


@pytest.mark.asyncio
@respx.mock
async def test_facebook_api_error_raises_meta_error():
    """Erro da API Facebook deve levantar MetaAPIError."""
    respx.post(f"{GRAPH_BASE}/{FB_ID}/photos").mock(
        return_value=Response(200, json={
            "error": {"code": 200, "message": "Permissions error"}
        })
    )

    with pytest.raises(MetaAPIError):
        await publish_to_facebook(FB_ID, TOKEN, IMAGE_URL, CAPTION)


# ─── collect_post_metrics ───────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_collect_metrics_returns_all_fields():
    """collect_post_metrics deve retornar impressions, reach, likes, comments."""
    post_id = "post-123"
    respx.get(f"{GRAPH_BASE}/{post_id}/insights").mock(
        return_value=Response(200, json={
            "data": [
                {"name": "impressions", "values": [{"value": 1500}]},
                {"name": "reach", "values": [{"value": 1200}]},
            ]
        })
    )
    respx.get(f"{GRAPH_BASE}/{post_id}").mock(
        return_value=Response(200, json={"like_count": 45, "comments_count": 8})
    )

    result = await collect_post_metrics(post_id, TOKEN)

    assert result["impressions"] == 1500
    assert result["reach"] == 1200
    assert result["likes"] == 45
    assert result["comments"] == 8
    assert "collected_at" in result


@pytest.mark.asyncio
@respx.mock
async def test_collect_metrics_handles_empty_insights():
    """Sem dados de insights deve retornar zeros."""
    post_id = "post-456"
    respx.get(f"{GRAPH_BASE}/{post_id}/insights").mock(
        return_value=Response(200, json={"data": []})
    )
    respx.get(f"{GRAPH_BASE}/{post_id}").mock(
        return_value=Response(200, json={})
    )

    result = await collect_post_metrics(post_id, TOKEN)

    assert result["impressions"] == 0
    assert result["reach"] == 0
    assert result["likes"] == 0
    assert result["comments"] == 0
