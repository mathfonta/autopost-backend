"""
Testes dos endpoints do Agente Scout no onboarding (Story 22.5).
Não conecta ao banco real — usa dependency overrides (mesmo padrão de
test_meta_oauth.py).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.auth import get_current_client
from app.core.database import get_db

CLIENT_ID = uuid.uuid4()


# ─── Helpers ─────────────────────────────────────────────────────

def _fake_client(scout_status: str = "pending", brand_profile: dict | None = None):
    client = MagicMock()
    client.id = CLIENT_ID
    client.is_active = True
    client.scout_status = scout_status
    client.brand_profile = brand_profile if brand_profile is not None else {"segment": "comércio"}
    return client


def _make_db(client=None):
    db = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = client
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


def _override_auth(client):
    async def _auth():
        return client
    return _auth


def _override_db(client):
    async def _db():
        yield _make_db(client)
    return _db


# ─── GET /onboarding/scout ───────────────────────────────────────

def test_get_scout_status_pending():
    """AC1 — status pending/running não retorna scout_insights."""
    client_mock = _fake_client(scout_status="running")
    app.dependency_overrides[get_current_client] = _override_auth(client_mock)

    with TestClient(app) as client:
        response = client.get("/onboarding/scout")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["scout_status"] == "running"
    assert body["scout_insights"] is None


def test_get_scout_status_done_includes_insights():
    """AC1 — status done retorna o scout_insights do brand_profile."""
    insights = {
        "refined_niche": "móveis planejados sob medida",
        "recurring_topics": ["cozinhas planejadas"],
        "visual_style": "madeira clara",
        "audience_notes": "casais",
        "suggested_segment": "construção civil",
        "confidence": 0.6,
    }
    client_mock = _fake_client(
        scout_status="done",
        brand_profile={"segment": "comércio", "scout_insights": insights},
    )
    app.dependency_overrides[get_current_client] = _override_auth(client_mock)

    with TestClient(app) as client:
        response = client.get("/onboarding/scout")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["scout_status"] == "done"
    assert body["scout_insights"]["refined_niche"] == "móveis planejados sob medida"
    assert body["scout_insights"]["suggested_segment"] == "construção civil"


def test_get_scout_status_skipped_no_insights():
    """AC5 — skipped/failed nunca expõe scout_insights, mesmo que exista no banco."""
    client_mock = _fake_client(
        scout_status="skipped",
        brand_profile={"segment": "comércio", "scout_insights": {"refined_niche": "não deveria aparecer"}},
    )
    app.dependency_overrides[get_current_client] = _override_auth(client_mock)

    with TestClient(app) as client:
        response = client.get("/onboarding/scout")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["scout_status"] == "skipped"
    assert body["scout_insights"] is None


def test_get_scout_status_defaults_to_pending_when_none():
    """scout_status nunca setado (None) retorna 'pending', não quebra."""
    client_mock = _fake_client(scout_status=None)
    app.dependency_overrides[get_current_client] = _override_auth(client_mock)

    with TestClient(app) as client:
        response = client.get("/onboarding/scout")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["scout_status"] == "pending"


# ─── POST /onboarding/scout/accept ───────────────────────────────

def test_accept_scout_suggestion_updates_segment():
    """AC4 — aceitar aplica o suggested_segment ao segment declarado."""
    insights = {"suggested_segment": "construção civil", "refined_niche": "obras residenciais"}
    client_mock = _fake_client(
        scout_status="done",
        brand_profile={"segment": "comércio", "company_name": "Empresa X", "scout_insights": insights},
    )
    app.dependency_overrides[get_current_client] = _override_auth(client_mock)
    app.dependency_overrides[get_db] = _override_db(client_mock)

    with TestClient(app) as client:
        response = client.post("/onboarding/scout/accept")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["updated"] is True
    assert body["segment"] == "construção civil"
    # Campos declarados preservados — só segment muda
    assert client_mock.brand_profile["segment"] == "construção civil"
    assert client_mock.brand_profile["company_name"] == "Empresa X"


def test_accept_scout_suggestion_without_suggestion_returns_400():
    """Sem suggested_segment disponível, retorna 400 — não aplica nada."""
    client_mock = _fake_client(
        scout_status="done",
        brand_profile={"segment": "comércio", "scout_insights": {"suggested_segment": None}},
    )
    app.dependency_overrides[get_current_client] = _override_auth(client_mock)
    app.dependency_overrides[get_db] = _override_db(client_mock)

    with TestClient(app) as client:
        response = client.post("/onboarding/scout/accept")

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert client_mock.brand_profile["segment"] == "comércio"  # intocado


def test_accept_scout_suggestion_ignores_client_submitted_segment():
    """Segurança: o endpoint IGNORA qualquer segmento enviado no corpo da
    requisição — só usa o que já está persistido no banco (AC4)."""
    insights = {"suggested_segment": "construção civil"}
    client_mock = _fake_client(
        scout_status="done",
        brand_profile={"segment": "comércio", "scout_insights": insights},
    )
    app.dependency_overrides[get_current_client] = _override_auth(client_mock)
    app.dependency_overrides[get_db] = _override_db(client_mock)

    with TestClient(app) as client:
        # Tenta injetar um segmento arbitrário no corpo — deve ser ignorado
        response = client.post("/onboarding/scout/accept", json={"segment": "segmento-malicioso"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["segment"] == "construção civil"
    assert client_mock.brand_profile["segment"] == "construção civil"


def test_accept_scout_suggestion_not_done_returns_400():
    """scout_status != done (mesmo com scout_insights presente de execução
    anterior) não permite aceitar — evita usar dado de uma análise incompleta."""
    client_mock = _fake_client(
        scout_status="running",
        brand_profile={"segment": "comércio", "scout_insights": {"suggested_segment": "construção civil"}},
    )
    app.dependency_overrides[get_current_client] = _override_auth(client_mock)
    app.dependency_overrides[get_db] = _override_db(client_mock)

    with TestClient(app) as client:
        response = client.post("/onboarding/scout/accept")

    app.dependency_overrides.clear()

    assert response.status_code == 400
