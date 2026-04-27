"""
Testes dos endpoints de ContentRequest.
Não conecta ao banco nem ao R2 — usa mocks.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.auth import get_current_client
from app.core.database import get_db
from app.models.content_request import ContentStatus

# ─── Helpers ────────────────────────────────────────────────────

CLIENT_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
FAKE_PHOTO_BYTES = b"\xff\xd8\xff"  # JPEG magic bytes (pequeno, dentro do limite)


def _fake_client():
    client = MagicMock()
    client.id = CLIENT_ID
    client.is_active = True
    return client


def _fake_content_request(status=ContentStatus.pending, client_id=None, retry_count=0):
    req = MagicMock()
    req.id = REQUEST_ID
    req.client_id = client_id or CLIENT_ID
    req.status = status
    req.photo_url = "https://r2.example.com/uploads/test.jpg"
    req.photo_key = f"uploads/{CLIENT_ID}/test.jpg"
    req.photo_keys = None
    req.photo_urls = None
    req.source_channel = "app"
    req.celery_task_id = "celery-task-abc"
    req.error_message = None
    req.analysis_result = None
    req.copy_result = None
    req.design_result = None
    req.publish_result = None
    req.caption_edited = False
    req.retry_count = retry_count
    req.content_type = None
    req.user_context = None
    req.created_at = datetime.now(timezone.utc)
    req.updated_at = datetime.now(timezone.utc)
    return req


def _make_db_with_request(req=None):
    db = AsyncMock(spec=AsyncSession)

    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none.return_value = req
    scalar_mock.scalar_one.return_value = 1 if req else 0
    scalar_mock.scalars.return_value.all.return_value = [req] if req else []

    db.execute = AsyncMock(return_value=scalar_mock)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


async def _auth_override():
    return _fake_client()


# ─── POST /content-requests ─────────────────────────────────────


def test_submit_photo_success():
    """Upload válido deve criar ContentRequest e retornar id + status."""
    fake_req = _fake_content_request()

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.upload_to_r2", new_callable=AsyncMock, return_value="https://r2.example.com/photo.jpg"),
        patch("app.tasks.pipeline.start_content_pipeline", return_value="task-123"),
    ):
        response = client.post(
            "/content-requests",
            files={"photo": ("test.jpg", FAKE_PHOTO_BYTES, "image/jpeg")},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["status"] == ContentStatus.pending


def test_submit_photo_invalid_format():
    """Arquivo com content_type inválido deve retornar 422."""
    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = lambda: _make_db_with_request()

    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            files={"photo": ("test.pdf", b"%PDF", "application/pdf")},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "formato inválido" in response.json()["detail"]


def test_submit_photo_too_large():
    """Arquivo acima de 20MB deve retornar 422."""
    large_bytes = b"\xff\xd8\xff" + b"0" * (21 * 1024 * 1024)  # ~21MB

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = lambda: _make_db_with_request()

    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            files={"photo": ("big.jpg", large_bytes, "image/jpeg")},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "grande" in response.json()["detail"]


def test_submit_photo_r2_failure():
    """Falha no R2 deve retornar 503."""
    async def _db_override():
        yield _make_db_with_request()

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.upload_to_r2", new_callable=AsyncMock, side_effect=Exception("R2 down")),
    ):
        response = client.post(
            "/content-requests",
            files={"photo": ("test.jpg", FAKE_PHOTO_BYTES, "image/jpeg")},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "armazenamento" in response.json()["detail"]


def test_submit_photo_triggers_pipeline():
    """Upload deve chamar start_content_pipeline com o request_id."""
    fake_req = _fake_content_request()
    pipeline_calls = []

    async def _db_override():
        db = _make_db_with_request(fake_req)
        yield db

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    def fake_pipeline(request_id):
        pipeline_calls.append(request_id)
        return "task-xyz"

    with (
        TestClient(app) as client,
        patch("app.api.content.upload_to_r2", new_callable=AsyncMock, return_value="https://r2.example.com/photo.jpg"),
        patch("app.tasks.pipeline.start_content_pipeline", side_effect=fake_pipeline),
    ):
        client.post(
            "/content-requests",
            files={"photo": ("test.jpg", FAKE_PHOTO_BYTES, "image/jpeg")},
        )

    app.dependency_overrides.clear()

    assert len(pipeline_calls) == 1


# ─── GET /content-requests/{id} ─────────────────────────────────


def test_get_content_request_success():
    """GET /{id} deve retornar o request com todos os campos."""
    fake_req = _fake_content_request()

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.generate_presigned_url", return_value="https://r2.example.com/uploads/test.jpg"),
    ):
        response = client.get(
            f"/content-requests/{REQUEST_ID}",
            headers={"Authorization": "Bearer token"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(REQUEST_ID)
    assert data["status"] == ContentStatus.pending
    assert data["photo_url"] == "https://r2.example.com/uploads/test.jpg"


def test_get_content_request_not_found():
    """GET /{id} com ID inexistente deve retornar 404."""
    async def _db_override():
        yield _make_db_with_request(None)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.get(
            f"/content-requests/{uuid.uuid4()}",
            headers={"Authorization": "Bearer token"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_get_content_request_wrong_client():
    """GET /{id} de outro cliente deve retornar 403."""
    other_client_req = _fake_content_request(client_id=uuid.uuid4())  # client_id diferente

    async def _db_override():
        yield _make_db_with_request(other_client_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.get(
            f"/content-requests/{REQUEST_ID}",
            headers={"Authorization": "Bearer token"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 403


# ─── GET /content-requests ──────────────────────────────────────


def test_list_content_requests_returns_paginated():
    """GET / deve retornar lista paginada."""
    fake_req = _fake_content_request()

    async def _db_override():
        db = AsyncMock(spec=AsyncSession)

        # Primeiro execute: count → retorna 1
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        # Segundo execute: items → retorna [fake_req]
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = [fake_req]

        db.execute = AsyncMock(side_effect=[count_result, items_result])
        yield db

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.get(
            "/content-requests",
            headers={"Authorization": "Bearer token"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["items"]) == 1


def test_list_content_requests_empty():
    """GET / sem requests deve retornar lista vazia."""
    async def _db_override():
        db = AsyncMock(spec=AsyncSession)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, items_result])
        yield db

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.get("/content-requests", headers={"Authorization": "Bearer token"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


# ─── PATCH /content-requests/{id} ──────────────────────────────


def test_patch_caption_success():
    """PATCH com status awaiting_approval deve atualizar a legenda."""
    fake_req = _fake_content_request(status=ContentStatus.awaiting_approval)
    fake_req.copy_result = {"caption": "legenda original", "hashtags": [], "cta": "", "suggested_time": ""}
    fake_req.caption_edited = False

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.patch(
            f"/content-requests/{REQUEST_ID}",
            json={"caption": "legenda editada pelo cliente"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake_req.caption_edited is True
    assert fake_req.copy_result["caption"] == "legenda editada pelo cliente"


def test_patch_caption_wrong_status():
    """PATCH com status diferente de awaiting_approval deve retornar 409."""
    fake_req = _fake_content_request(status=ContentStatus.published)

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.patch(
            f"/content-requests/{REQUEST_ID}",
            json={"caption": "nova legenda"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "awaiting_approval" in response.json()["detail"]


def test_patch_caption_wrong_client():
    """PATCH de outro cliente deve retornar 403."""
    other_req = _fake_content_request(
        status=ContentStatus.awaiting_approval,
        client_id=uuid.uuid4(),
    )

    async def _db_override():
        yield _make_db_with_request(other_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.patch(
            f"/content-requests/{REQUEST_ID}",
            json={"caption": "hack"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 403


# ─── POST /content-requests/{id}/retry ──────────────────────────


def test_retry_success():
    """Retry com status awaiting_approval e count < 3 deve disparar nova geração."""
    fake_req = _fake_content_request(status=ContentStatus.awaiting_approval, retry_count=0)

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.retry_generate_copy") as mock_retry,
    ):
        mock_retry.delay = MagicMock()
        response = client.post(f"/content-requests/{REQUEST_ID}/retry")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["retry_count"] == 1
    assert fake_req.retry_count == 1


def test_retry_max_reached():
    """Retry com retry_count >= 3 deve retornar 422."""
    fake_req = _fake_content_request(status=ContentStatus.awaiting_approval, retry_count=3)

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/retry")

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "Máximo" in response.json()["detail"]


def test_retry_wrong_status():
    """Retry com status != awaiting_approval deve retornar 409."""
    fake_req = _fake_content_request(status=ContentStatus.published)

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(f"/content-requests/{REQUEST_ID}/retry")

    app.dependency_overrides.clear()

    assert response.status_code == 409


def test_submit_photo_with_content_type():
    """Upload com content_type deve salvar o campo no request."""
    fake_req = _fake_content_request()
    fake_req.content_type = "obra_concluida"

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.upload_to_r2", new_callable=AsyncMock, return_value="https://r2.example.com/photo.jpg"),
        patch("app.tasks.pipeline.start_content_pipeline", return_value="task-123"),
    ):
        response = client.post(
            "/content-requests",
            data={"content_type": "obra_concluida"},
            files={"photo": ("test.jpg", FAKE_PHOTO_BYTES, "image/jpeg")},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 201


def test_submit_photo_requires_auth():
    """POST sem autenticação deve retornar 403 (sem Bearer header)."""
    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            files={"photo": ("test.jpg", FAKE_PHOTO_BYTES, "image/jpeg")},
        )

    # FastAPI HTTPBearer retorna 401 quando o header Authorization está ausente
    assert response.status_code == 401


# ─── Story 6.1 — Multi-foto ─────────────────────────────────────


def test_submit_multi_photo_carousel_success():
    """Upload de 2 fotos com content_type=carousel deve retornar 201."""
    fake_req = _fake_content_request()
    fake_req.content_type = "carousel"
    fake_req.photo_keys = [f"uploads/{CLIENT_ID}/a.jpg", f"uploads/{CLIENT_ID}/b.jpg"]
    fake_req.photo_urls = ["https://r2.example.com/a.jpg", "https://r2.example.com/b.jpg"]

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.upload_to_r2", new_callable=AsyncMock, return_value="https://r2.example.com/photo.jpg"),
        patch("app.tasks.pipeline.start_content_pipeline", return_value="task-123"),
    ):
        response = client.post(
            "/content-requests",
            data={"content_type": "carousel"},
            files=[
                ("photos", ("a.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
                ("photos", ("b.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
            ],
        )

    app.dependency_overrides.clear()

    assert response.status_code == 201


def test_submit_multi_photo_before_after_success():
    """Upload de exatamente 2 fotos com content_type=before_after deve retornar 201."""
    fake_req = _fake_content_request()
    fake_req.content_type = "before_after"
    fake_req.photo_keys = [f"uploads/{CLIENT_ID}/antes.jpg", f"uploads/{CLIENT_ID}/depois.jpg"]
    fake_req.photo_urls = ["https://r2.example.com/antes.jpg", "https://r2.example.com/depois.jpg"]

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.upload_to_r2", new_callable=AsyncMock, return_value="https://r2.example.com/photo.jpg"),
        patch("app.tasks.pipeline.start_content_pipeline", return_value="task-123"),
    ):
        response = client.post(
            "/content-requests",
            data={"content_type": "before_after"},
            files=[
                ("photos", ("antes.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
                ("photos", ("depois.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
            ],
        )

    app.dependency_overrides.clear()

    assert response.status_code == 201


def test_submit_retrocompat_single_photo_field():
    """Upload com campo legado `photo` deve continuar funcionando."""
    fake_req = _fake_content_request()
    fake_req.photo_keys = [f"uploads/{CLIENT_ID}/test.jpg"]
    fake_req.photo_urls = ["https://r2.example.com/test.jpg"]

    async def _db_override():
        yield _make_db_with_request(fake_req)

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with (
        TestClient(app) as client,
        patch("app.api.content.upload_to_r2", new_callable=AsyncMock, return_value="https://r2.example.com/test.jpg"),
        patch("app.tasks.pipeline.start_content_pipeline", return_value="task-abc"),
    ):
        response = client.post(
            "/content-requests",
            files={"photo": ("test.jpg", FAKE_PHOTO_BYTES, "image/jpeg")},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 201
    assert "id" in response.json()


def test_submit_no_photo_returns_422():
    """POST sem nenhuma foto deve retornar 422."""
    async def _db_override():
        yield _make_db_with_request()

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            data={"content_type": "post_simples"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "obrigatória" in response.json()["detail"]


def test_submit_before_after_requires_exactly_2_photos():
    """before_after com 1 foto deve retornar 422."""
    async def _db_override():
        yield _make_db_with_request()

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            data={"content_type": "before_after"},
            files=[("photos", ("only.jpg", FAKE_PHOTO_BYTES, "image/jpeg"))],
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "before_after" in response.json()["detail"]
    assert "2" in response.json()["detail"]


def test_submit_before_after_rejects_3_photos():
    """before_after com 3 fotos deve retornar 422."""
    async def _db_override():
        yield _make_db_with_request()

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            data={"content_type": "before_after"},
            files=[
                ("photos", ("a.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
                ("photos", ("b.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
                ("photos", ("c.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
            ],
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "before_after" in response.json()["detail"]


def test_submit_carousel_requires_at_least_2_photos():
    """carousel com 1 foto deve retornar 422."""
    async def _db_override():
        yield _make_db_with_request()

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            data={"content_type": "carousel"},
            files=[("photos", ("only.jpg", FAKE_PHOTO_BYTES, "image/jpeg"))],
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "carousel" in response.json()["detail"]


def test_submit_simple_type_rejects_2_photos():
    """Tipos simples com 2 fotos devem retornar 422."""
    async def _db_override():
        yield _make_db_with_request()

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            data={"content_type": "post_simples"},
            files=[
                ("photos", ("a.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
                ("photos", ("b.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
            ],
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "simples" in response.json()["detail"]


def test_submit_invalid_content_type_returns_422():
    """content_type inválido deve retornar 422."""
    async def _db_override():
        yield _make_db_with_request()

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    with TestClient(app) as client:
        response = client.post(
            "/content-requests",
            data={"content_type": "tipo_invalido_xyz"},
            files=[("photos", ("a.jpg", FAKE_PHOTO_BYTES, "image/jpeg"))],
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "inválido" in response.json()["detail"]


def test_submit_multi_photo_invalid_format_in_second_photo():
    """Formato inválido na segunda foto deve retornar 422 com número da foto."""
    async def _db_override():
        yield _make_db_with_request()

    app.dependency_overrides[get_current_client] = _auth_override
    app.dependency_overrides[get_db] = _db_override

    # foto 1 passa validação e sobe para R2; foto 2 falha na validação de formato
    with (
        TestClient(app) as client,
        patch("app.api.content.upload_to_r2", new_callable=AsyncMock, return_value="https://r2.example.com/a.jpg"),
    ):
        response = client.post(
            "/content-requests",
            data={"content_type": "carousel"},
            files=[
                ("photos", ("a.jpg", FAKE_PHOTO_BYTES, "image/jpeg")),
                ("photos", ("b.pdf", b"%PDF", "application/pdf")),
            ],
        )

    app.dependency_overrides.clear()

    assert response.status_code == 422
    assert "Foto 2" in response.json()["detail"]


def test_freshen_urls_multi_photo():
    """_freshen_urls deve regenerar photo_urls a partir de photo_keys."""
    from app.api.content import _freshen_urls

    fake_req = _fake_content_request()
    fake_req.photo_keys = [
        f"uploads/{CLIENT_ID}/a.jpg",
        f"uploads/{CLIENT_ID}/b.jpg",
    ]
    fake_req.photo_urls = None
    fake_req.design_result = None

    with patch("app.api.content.generate_presigned_url", side_effect=lambda key, ttl: f"https://fresh.r2/{key}"):
        result = _freshen_urls(fake_req)

    assert result.photo_urls is not None
    assert len(result.photo_urls) == 2
    assert "a.jpg" in result.photo_urls[0]
    assert "b.jpg" in result.photo_urls[1]


def test_freshen_urls_single_photo_retrocompat():
    """_freshen_urls com foto única não deve quebrar (retrocompat)."""
    from app.api.content import _freshen_urls

    fake_req = _fake_content_request()
    fake_req.photo_keys = None
    fake_req.photo_urls = None
    fake_req.design_result = None

    with patch("app.api.content.generate_presigned_url", return_value="https://fresh.r2/test.jpg"):
        result = _freshen_urls(fake_req)

    assert result.photo_url == "https://fresh.r2/test.jpg"
    assert result.photo_urls is None
