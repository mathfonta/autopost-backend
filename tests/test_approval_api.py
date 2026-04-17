"""
Testes dos endpoints de aprovação e rejeição de ContentRequest.
Não conecta ao banco nem ao Celery — usa mocks.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.auth import get_current_client
from app.core.database import get_db
from app.models.content_request import ContentStatus

# ─── Helpers ────────────────────────────────────────────────────

CLIENT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()


def _fake_client():
    client = MagicMock()
    client.id = CLIENT_ID
    client.is_active = True
    return client


def _fake_req(status=ContentStatus.awaiting_approval, client_id=None):
    req = MagicMock()
    req.id = REQUEST_ID
    req.client_id = client_id or CLIENT_ID
    req.status = status
    req.error_message = None
    req.created_at = datetime.now(timezone.utc)
    req.updated_at = datetime.now(timezone.utc)
    return req


def _make_db(req=None):
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = req
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


async def _auth_override():
    return _fake_client()


# ─── POST /{id}/approve ─────────────────────────────────────────


def test_approve_success():
    """Aprovação de request em awaiting_approval deve disparar publish_post."""
    req = _fake_req(status=ContentStatus.awaiting_approval)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.publish_post") as mock_publish,
    ):
        mock_publish.delay = MagicMock(return_value=None)
        response = client.post(f"/content-requests/{REQUEST_ID}/approve")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(REQUEST_ID)
    assert data["status"] == ContentStatus.publishing


def test_approve_triggers_publish_post():
    """Aprovação deve chamar publish_post.delay com o request_id correto."""
    req = _fake_req(status=ContentStatus.awaiting_approval)
    delay_calls = []

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.publish_post") as mock_publish,
    ):
        mock_publish.delay = MagicMock(side_effect=lambda rid: delay_calls.append(rid))
        client.post(f"/content-requests/{REQUEST_ID}/approve")

    app.dependency_overrides.clear()

    assert len(delay_calls) == 1
    assert delay_calls[0] == str(REQUEST_ID)


def test_approve_wrong_status_returns_409():
    """Aprovação de request em status diferente de awaiting_approval → 409."""
    req = _fake_req(status=ContentStatus.pending)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/approve")

    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "pending" in response.json()["detail"]


def test_approve_not_found_returns_404():
    """Aprovação de request inexistente → 404."""
    async def _db_override():
        yield _make_db(None)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{uuid.uuid4()}/approve")

    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_approve_wrong_client_returns_403():
    """Aprovação de request de outro cliente → 403."""
    req = _fake_req(status=ContentStatus.awaiting_approval, client_id=uuid.uuid4())

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/approve")

    app.dependency_overrides.clear()

    assert response.status_code == 403


# ─── POST /{id}/reject ──────────────────────────────────────────


def test_reject_success():
    """Rejeição deve marcar status como failed."""
    req = _fake_req(status=ContentStatus.awaiting_approval)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            f"/content-requests/{REQUEST_ID}/reject",
            json={"reason": "Não gostei da foto"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == ContentStatus.failed


def test_reject_saves_reason():
    """Rejeição com motivo deve salvar mensagem de erro."""
    req = _fake_req(status=ContentStatus.awaiting_approval)
    saved_message = []

    async def _db_override():
        db = _make_db(req)
        original_commit = db.commit

        async def fake_commit():
            saved_message.append(req.error_message)
            await original_commit()

        db.commit = fake_commit
        yield db

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        client.post(
            f"/content-requests/{REQUEST_ID}/reject",
            json={"reason": "Imagem desfocada"},
        )

    app.dependency_overrides.clear()

    assert len(saved_message) == 1
    assert "Imagem desfocada" in saved_message[0]


def test_reject_without_reason():
    """Rejeição sem motivo deve usar mensagem padrão."""
    req = _fake_req(status=ContentStatus.awaiting_approval)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/reject")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert req.error_message == "Rejeitado pelo cliente"


def test_reject_wrong_client_returns_403():
    """Rejeição de request de outro cliente → 403."""
    req = _fake_req(client_id=uuid.uuid4())

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/reject")

    app.dependency_overrides.clear()

    assert response.status_code == 403
