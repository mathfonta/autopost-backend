"""
Testes de autenticação — usam dependency_overrides para isolar o banco
e mock do Supabase Auth para não depender de rede.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.database import get_db
from app.core.auth import get_current_client


# ─── Helpers ────────────────────────────────────────────────────


def _make_supabase_session(user_id: str | None = None):
    """Retorna (mock de AuthResponse, uid) para Supabase."""
    uid = user_id or str(uuid.uuid4())
    response = MagicMock()
    response.user = MagicMock()
    response.user.id = uid
    response.session = MagicMock()
    response.session.access_token = "mock-access-token"
    response.session.refresh_token = "mock-refresh-token"
    response.session.expires_in = 3600
    return response, uid


def _make_db(scalar_return=None):
    """Retorna uma sessão de banco mockada."""
    db = AsyncMock(spec=AsyncSession)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = scalar_return
    db.execute = AsyncMock(return_value=result_mock)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


async def _db_override_none():
    """Dependency override: DB sem cliente existente."""
    yield _make_db(scalar_return=None)


# ─── Register ───────────────────────────────────────────────────


def test_register_success():
    auth_response, uid = _make_supabase_session()

    app.dependency_overrides[get_db] = _db_override_none

    with (
        TestClient(app) as client,
        patch("app.api.auth.supabase_sign_up", new_callable=AsyncMock, return_value=auth_response),
    ):
        response = client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "Senha123!", "name": "Teste"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert data["access_token"] == "mock-access-token"
    assert data["refresh_token"] == "mock-refresh-token"
    assert data["token_type"] == "bearer"


def test_register_duplicate_email():
    from app.models.client import Client

    existing = MagicMock(spec=Client)
    existing.email = "dup@example.com"

    async def _db_with_existing():
        yield _make_db(scalar_return=existing)

    app.dependency_overrides[get_db] = _db_with_existing

    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": "Senha123!", "name": "Dup"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "Email já cadastrado" in response.json()["detail"]


def test_register_supabase_error():
    app.dependency_overrides[get_db] = _db_override_none

    with (
        TestClient(app) as client,
        patch("app.api.auth.supabase_sign_up", new_callable=AsyncMock, side_effect=Exception("Supabase down")),
    ):
        response = client.post(
            "/auth/register",
            json={"email": "err@example.com", "password": "Senha123!", "name": "Err"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Erro ao criar conta" in response.json()["detail"]


# ─── Login ──────────────────────────────────────────────────────


def test_login_success():
    auth_response, _ = _make_supabase_session()

    with (
        TestClient(app) as client,
        patch("app.api.auth.supabase_sign_in", new_callable=AsyncMock, return_value=auth_response),
    ):
        response = client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "Senha123!"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"] == "mock-access-token"
    assert data["token_type"] == "bearer"


def test_login_wrong_credentials():
    with (
        TestClient(app) as client,
        patch("app.api.auth.supabase_sign_in", new_callable=AsyncMock, side_effect=Exception("Invalid")),
    ):
        response = client.post(
            "/auth/login",
            json={"email": "bad@example.com", "password": "errada"},
        )

    assert response.status_code == 401
    assert "Email ou senha incorretos" in response.json()["detail"]


def test_login_no_session():
    auth_response = MagicMock()
    auth_response.session = None

    with (
        TestClient(app) as client,
        patch("app.api.auth.supabase_sign_in", new_callable=AsyncMock, return_value=auth_response),
    ):
        response = client.post(
            "/auth/login",
            json={"email": "nosession@example.com", "password": "Senha123!"},
        )

    assert response.status_code == 401


# ─── Refresh ────────────────────────────────────────────────────


def test_refresh_success():
    auth_response, _ = _make_supabase_session()

    with (
        TestClient(app) as client,
        patch("app.api.auth.supabase_refresh", new_callable=AsyncMock, return_value=auth_response),
    ):
        response = client.post("/auth/refresh", json={"refresh_token": "valid-refresh"})

    assert response.status_code == 200
    assert response.json()["access_token"] == "mock-access-token"


def test_refresh_invalid_token():
    with (
        TestClient(app) as client,
        patch("app.api.auth.supabase_refresh", new_callable=AsyncMock, side_effect=Exception("Expired")),
    ):
        response = client.post("/auth/refresh", json={"refresh_token": "expired-token"})

    assert response.status_code == 401
    assert "Refresh token inválido" in response.json()["detail"]


# ─── Me ─────────────────────────────────────────────────────────


def test_me_authenticated():
    from app.models.client import Client

    fake_client = MagicMock(spec=Client)
    fake_client.id = uuid.uuid4()
    fake_client.email = "me@example.com"
    fake_client.name = "Meu Nome"
    fake_client.plan = "starter"
    fake_client.brand_profile = {}
    fake_client.is_active = True
    fake_client.voice_tone = "casual"

    async def _override_auth():
        return fake_client

    app.dependency_overrides[get_current_client] = _override_auth
    try:
        with TestClient(app) as client:
            response = client.get(
                "/auth/me",
                headers={"Authorization": "Bearer valid-token"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


def test_me_unauthenticated():
    with TestClient(app) as client:
        response = client.get("/auth/me")

    # HTTPBearer retorna 401 quando não há header Authorization
    assert response.status_code == 401
