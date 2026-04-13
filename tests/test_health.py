"""
Testes do endpoint /health.
Usa dependency_overrides do FastAPI para não precisar de banco/Redis reais.
"""

import pytest
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport

# conftest.py já definiu os env vars antes deste import
from app.main import app
from app.core.database import get_db
from app.core.redis import get_redis


# ─── Helpers ─────────────────────────────────────────────────

def make_db_ok():
    mock = AsyncMock()
    mock.execute = AsyncMock(return_value=None)
    return mock


def make_db_error():
    mock = AsyncMock()
    mock.execute = AsyncMock(side_effect=Exception("connection refused"))
    return mock


def make_redis_ok():
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    return mock


def make_redis_error():
    mock = AsyncMock()
    mock.ping = AsyncMock(side_effect=Exception("redis timeout"))
    return mock


# ─── Fixture de cliente ───────────────────────────────────────

@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ─── Testes ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_health_all_ok():
    """Todos os serviços OK → status 'ok' e HTTP 200."""
    app.dependency_overrides[get_db] = lambda: make_db_ok()
    app.dependency_overrides[get_redis] = lambda: make_redis_ok()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["services"]["api"] == "ok"
    assert body["services"]["database"] == "ok"
    assert body["services"]["redis"] == "ok"
    assert body["version"] == "1.0.0"


@pytest.mark.anyio
async def test_health_db_error():
    """Banco com erro → status 'degraded'."""
    app.dependency_overrides[get_db] = lambda: make_db_error()
    app.dependency_overrides[get_redis] = lambda: make_redis_ok()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["services"]["database"].startswith("error:")


@pytest.mark.anyio
async def test_health_redis_error():
    """Redis com erro → status 'degraded'."""
    app.dependency_overrides[get_db] = lambda: make_db_ok()
    app.dependency_overrides[get_redis] = lambda: make_redis_error()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health")

    app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["services"]["redis"].startswith("error:")


@pytest.mark.anyio
async def test_health_response_shape():
    """Resposta tem todos os campos esperados."""
    app.dependency_overrides[get_db] = lambda: make_db_ok()
    app.dependency_overrides[get_redis] = lambda: make_redis_ok()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health")

    app.dependency_overrides.clear()

    body = resp.json()
    assert {"status", "version", "env", "services"} <= body.keys()
    assert {"api", "database", "redis"} <= body["services"].keys()
