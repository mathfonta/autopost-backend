"""
Testes do endpoint de agendamento de ContentRequest (Story 19.1).
Não conecta ao banco nem ao Celery — usa mocks.
"""

import uuid
from datetime import datetime, timedelta, timezone
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
    req.scheduled_for = None
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


def _future_iso(days=1):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# ─── POST /{id}/schedule ────────────────────────────────────────


def test_schedule_success():
    """Agendar request em awaiting_approval deve setar status=scheduled e scheduled_for."""
    req = _fake_req(status=ContentStatus.awaiting_approval)
    scheduled_for = _future_iso(days=1)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": scheduled_for},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(REQUEST_ID)
    assert data["status"] == ContentStatus.scheduled
    assert req.status == ContentStatus.scheduled
    assert req.scheduled_for is not None


def test_schedule_does_not_trigger_publish():
    """Agendar NÃO deve chamar publish_post — quem publica é o Beat da Story 19.2."""
    req = _fake_req(status=ContentStatus.awaiting_approval)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.publish_post") as mock_publish,
    ):
        mock_publish.delay = MagicMock()
        client.post(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": _future_iso(days=1)},
        )

    app.dependency_overrides.clear()

    mock_publish.delay.assert_not_called()


def test_schedule_past_datetime_returns_422():
    """scheduled_for no passado → 422."""
    req = _fake_req(status=ContentStatus.awaiting_approval)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": past},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422


def test_schedule_too_far_future_returns_422():
    """scheduled_for a mais de 30 dias no futuro → 422."""
    req = _fake_req(status=ContentStatus.awaiting_approval)
    too_far = _future_iso(days=31)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": too_far},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422


def test_schedule_wrong_status_returns_409():
    """Agendar request que não está em awaiting_approval → 409."""
    req = _fake_req(status=ContentStatus.pending)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": _future_iso(days=1)},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "pending" in response.json()["detail"]


def test_schedule_not_found_returns_404():
    """Agendar request inexistente → 404."""
    async def _db_override():
        yield _make_db(None)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            f"/content-requests/{uuid.uuid4()}/schedule",
            json={"scheduled_for": _future_iso(days=1)},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_schedule_wrong_client_returns_403():
    """Agendar request de outro cliente → 403."""
    req = _fake_req(status=ContentStatus.awaiting_approval, client_id=uuid.uuid4())

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": _future_iso(days=1)},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 403


# ─── POST /{id}/schedule/cancel (Story 19.2) ─────────────────────


def test_cancel_success():
    """Cancelar agendamento devolve para awaiting_approval e zera scheduled_for."""
    req = _fake_req(status=ContentStatus.scheduled)
    req.scheduled_for = datetime.now(timezone.utc) + timedelta(days=1)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/schedule/cancel")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == ContentStatus.awaiting_approval
    assert req.status == ContentStatus.awaiting_approval
    assert req.scheduled_for is None


def test_cancel_wrong_status_returns_409():
    """Cancelar request que não está scheduled → 409."""
    req = _fake_req(status=ContentStatus.awaiting_approval)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/schedule/cancel")

    app.dependency_overrides.clear()

    assert response.status_code == 409


def test_cancel_not_found_returns_404():
    """Cancelar request inexistente → 404."""
    async def _db_override():
        yield _make_db(None)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{uuid.uuid4()}/schedule/cancel")

    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_cancel_wrong_client_returns_403():
    """Cancelar agendamento de outro cliente → 403."""
    req = _fake_req(status=ContentStatus.scheduled, client_id=uuid.uuid4())

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/schedule/cancel")

    app.dependency_overrides.clear()

    assert response.status_code == 403


# ─── PATCH /{id}/schedule — reagendar (Story 19.2) ───────────────


def test_reschedule_success():
    """Reagendar atualiza scheduled_for mantendo status=scheduled."""
    req = _fake_req(status=ContentStatus.scheduled)
    req.scheduled_for = datetime.now(timezone.utc) + timedelta(days=1)
    new_time = _future_iso(days=5)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.patch(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": new_time},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == ContentStatus.scheduled
    assert req.status == ContentStatus.scheduled
    assert req.scheduled_for is not None


def test_reschedule_wrong_status_returns_409():
    """Reagendar request que não está scheduled → 409."""
    req = _fake_req(status=ContentStatus.awaiting_approval)

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.patch(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": _future_iso(days=1)},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 409


def test_reschedule_past_datetime_returns_422():
    """Reagendar para o passado → 422."""
    req = _fake_req(status=ContentStatus.scheduled)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.patch(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": past},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422


def test_reschedule_not_found_returns_404():
    """Reagendar request inexistente → 404."""
    async def _db_override():
        yield _make_db(None)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.patch(
            f"/content-requests/{uuid.uuid4()}/schedule",
            json={"scheduled_for": _future_iso(days=1)},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_reschedule_wrong_client_returns_403():
    """Reagendar post de outro cliente → 403."""
    req = _fake_req(status=ContentStatus.scheduled, client_id=uuid.uuid4())

    async def _db_override():
        yield _make_db(req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.patch(
            f"/content-requests/{REQUEST_ID}/schedule",
            json={"scheduled_for": _future_iso(days=1)},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 403
