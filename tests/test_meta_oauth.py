"""
Testes dos endpoints OAuth Meta.
Não conecta ao banco nem à Graph API — usa respx (httpx mock) e dependency overrides.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import respx
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.auth import get_current_client
from app.core.database import get_db

# ─── Constantes de teste ─────────────────────────────────────────

CLIENT_ID = uuid.uuid4()
JWT_SECRET = "test-secret-meta-oauth"

MOCK_PAGES_RESP = {
    "data": [
        {"id": "page-111", "name": "Empresa Teste", "access_token": "page-token-abc"}
    ]
}
MOCK_PAGE_IG_RESP = {
    "id": "page-111",
    "instagram_business_account": {"id": "ig-222"},
}
MOCK_IG_USER_RESP = {"id": "ig-222", "username": "empresa_teste_ig"}


# ─── Helpers ─────────────────────────────────────────────────────

def _fake_client(connected: bool = False):
    client = MagicMock()
    client.id = CLIENT_ID
    client.is_active = True
    client.meta_access_token = "long-token-xyz" if connected else None
    client.meta_token_expires_at = (
        datetime.now(timezone.utc) + timedelta(days=60) if connected else None
    )
    client.instagram_business_id = "ig-222" if connected else None
    client.instagram_username = "empresa_teste_ig" if connected else None
    client.facebook_page_id = "page-111" if connected else None
    client.facebook_page_name = "Empresa Teste" if connected else None
    return client


def _make_db(client=None):
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = client
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


async def _auth_override():
    return _fake_client()


async def _auth_connected_override():
    return _fake_client(connected=True)


def _make_state(client_id=None, secret=JWT_SECRET):
    payload = {
        "client_id": str(client_id or CLIENT_ID),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _mock_settings(secret=JWT_SECRET):
    settings = MagicMock()
    settings.JWT_SECRET = secret
    settings.META_APP_ID = "test-app-id"
    settings.META_APP_SECRET = "test-app-secret"
    settings.META_REDIRECT_URI = "https://example.com/meta/callback"
    return settings


# ─── GET /meta/connect ───────────────────────────────────────────


def test_connect_returns_auth_url():
    """GET /meta/connect deve retornar um auth_url com os campos obrigatórios."""
    app.dependency_overrides[get_current_client] = _auth_override

    with patch("app.api.meta.get_settings", return_value=_mock_settings()):
        with TestClient(app) as client:
            response = client.get("/meta/connect")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert "auth_url" in data
    assert "test-app-id" in data["auth_url"]
    assert "instagram_basic" in data["auth_url"]
    assert "instagram_content_publish" in data["auth_url"]


def test_connect_state_contains_client_id():
    """O state gerado em /connect deve ser um JWT com o client_id correto."""
    app.dependency_overrides[get_current_client] = _auth_override

    with patch("app.api.meta.get_settings", return_value=_mock_settings()):
        with TestClient(app) as client:
            response = client.get("/meta/connect")

    app.dependency_overrides.clear()

    auth_url = response.json()["auth_url"]
    params = parse_qs(urlparse(auth_url).query)
    state = params["state"][0]

    payload = jwt.decode(state, JWT_SECRET, algorithms=["HS256"])
    assert payload["client_id"] == str(CLIENT_ID)


def test_connect_requires_auth():
    """GET /meta/connect sem Bearer token deve retornar 403."""
    with TestClient(app) as client:
        response = client.get("/meta/connect")
    assert response.status_code in (401, 403)


# ─── GET /meta/callback ──────────────────────────────────────────


def test_callback_success():
    """Callback com code válido deve retornar connected: true com dados do IG."""
    client_mock = _fake_client()
    state = _make_state()

    async def _db_override():
        yield _make_db(client_mock)

    app.dependency_overrides[get_db] = _db_override

    with respx.mock:
        respx.post("https://graph.facebook.com/v21.0/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "short-token-111"})
        )
        respx.get("https://graph.facebook.com/v21.0/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "long-token-xyz"})
        )
        respx.get("https://graph.facebook.com/v21.0/me/accounts").mock(
            return_value=httpx.Response(200, json=MOCK_PAGES_RESP)
        )
        respx.get("https://graph.facebook.com/v21.0/page-111").mock(
            return_value=httpx.Response(200, json=MOCK_PAGE_IG_RESP)
        )
        respx.get("https://graph.facebook.com/v21.0/ig-222").mock(
            return_value=httpx.Response(200, json=MOCK_IG_USER_RESP)
        )

        with patch("app.api.meta.get_settings", return_value=_mock_settings()):
            with TestClient(app) as client:
                response = client.get(f"/meta/callback?code=auth-code-abc&state={state}")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert data["instagram_username"] == "empresa_teste_ig"
    assert data["facebook_page_name"] == "Empresa Teste"


def test_callback_saves_token_and_ids():
    """Callback deve persistir meta_access_token, IDs e username no Client."""
    client_mock = _fake_client()
    state = _make_state()

    async def _db_override():
        yield _make_db(client_mock)

    app.dependency_overrides[get_db] = _db_override

    with respx.mock:
        respx.post("https://graph.facebook.com/v21.0/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "short-token-111"})
        )
        respx.get("https://graph.facebook.com/v21.0/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "long-token-xyz"})
        )
        respx.get("https://graph.facebook.com/v21.0/me/accounts").mock(
            return_value=httpx.Response(200, json=MOCK_PAGES_RESP)
        )
        respx.get("https://graph.facebook.com/v21.0/page-111").mock(
            return_value=httpx.Response(200, json=MOCK_PAGE_IG_RESP)
        )
        respx.get("https://graph.facebook.com/v21.0/ig-222").mock(
            return_value=httpx.Response(200, json=MOCK_IG_USER_RESP)
        )

        with patch("app.api.meta.get_settings", return_value=_mock_settings()):
            with TestClient(app) as client:
                client.get(f"/meta/callback?code=auth-code-abc&state={state}")

    app.dependency_overrides.clear()

    assert client_mock.meta_access_token == "long-token-xyz"
    assert client_mock.instagram_business_id == "ig-222"
    assert client_mock.instagram_username == "empresa_teste_ig"
    assert client_mock.facebook_page_id == "page-111"
    assert client_mock.facebook_page_name == "Empresa Teste"
    assert client_mock.meta_token_expires_at is not None


def test_callback_invalid_state_returns_400():
    """Callback com state inválido/expirado deve retornar 400."""
    async def _db_override():
        yield _make_db(None)

    app.dependency_overrides[get_db] = _db_override

    with patch("app.api.meta.get_settings", return_value=_mock_settings()):
        with TestClient(app) as client:
            response = client.get("/meta/callback?code=abc&state=token-invalido")

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "State inválido" in response.json()["detail"]


def test_callback_expired_state_returns_400():
    """Callback com state JWT expirado deve retornar 400."""
    expired_payload = {
        "client_id": str(CLIENT_ID),
        "exp": datetime.now(timezone.utc) - timedelta(minutes=10),
    }
    expired_state = jwt.encode(expired_payload, JWT_SECRET, algorithm="HS256")

    async def _db_override():
        yield _make_db(None)

    app.dependency_overrides[get_db] = _db_override

    with patch("app.api.meta.get_settings", return_value=_mock_settings()):
        with TestClient(app) as client:
            response = client.get(f"/meta/callback?code=abc&state={expired_state}")

    app.dependency_overrides.clear()

    assert response.status_code == 400


# ─── GET /meta/status ────────────────────────────────────────────


def test_status_not_connected():
    """GET /meta/status sem token salvo deve retornar connected: false."""
    app.dependency_overrides[get_current_client] = _auth_override

    with TestClient(app) as client:
        response = client.get("/meta/status")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert data["instagram_username"] is None
    assert data["facebook_page_name"] is None
    assert data["token_expires_at"] is None


def test_status_connected():
    """GET /meta/status com token salvo deve retornar dados da conta."""
    app.dependency_overrides[get_current_client] = _auth_connected_override

    with TestClient(app) as client:
        response = client.get("/meta/status")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert data["instagram_username"] == "empresa_teste_ig"
    assert data["facebook_page_name"] == "Empresa Teste"
    assert data["token_expires_at"] is not None


def test_status_requires_auth():
    """GET /meta/status sem Bearer token deve retornar 401/403."""
    with TestClient(app) as client:
        response = client.get("/meta/status")
    assert response.status_code in (401, 403)
