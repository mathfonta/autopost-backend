"""
Testes de multi-tenancy — TenantMixin, require_ownership e tenant_filter.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import Integer, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.tenant import require_ownership, tenant_filter
from app.models.client import Client
from app.models.mixins import TenantMixin
from app.core.database import Base


# ─── Modelos de teste (declarados no escopo do módulo) ──────────


class FakePost(Base, TenantMixin):
    __tablename__ = "fake_posts_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class FakeResource(Base, TenantMixin):
    __tablename__ = "fake_resources_test"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


# ─── Helpers ────────────────────────────────────────────────────


def _make_client(client_id: uuid.UUID | None = None) -> Client:
    c = MagicMock(spec=Client)
    c.id = client_id or uuid.uuid4()
    return c


# ─── TenantMixin ────────────────────────────────────────────────


def test_tenant_mixin_has_client_id_column():
    """TenantMixin deve expor a coluna client_id."""
    assert hasattr(TenantMixin, "client_id")


def test_tenant_mixin_applied_to_model():
    """Um modelo com TenantMixin deve ter client_id como coluna mapeada."""
    cols = [c.name for c in FakePost.__table__.columns]
    assert "client_id" in cols


def test_tenant_mixin_creates_index():
    """TenantMixin deve criar índice em client_id."""
    index_names = {idx.name for idx in FakePost.__table__.indexes}
    assert any("client_id" in name for name in index_names)


# ─── require_ownership ──────────────────────────────────────────


def test_require_ownership_same_client():
    """Não deve levantar exceção quando resource pertence ao client."""
    cid = uuid.uuid4()
    client = _make_client(cid)
    require_ownership(cid, client)  # deve passar sem erro


def test_require_ownership_different_client():
    """Deve levantar 403 quando resource pertence a outro client."""
    client = _make_client()
    other_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        require_ownership(other_id, client)

    assert exc_info.value.status_code == 403
    assert "Acesso negado" in exc_info.value.detail


# ─── tenant_filter ──────────────────────────────────────────────


def test_tenant_filter_adds_where_clause():
    """tenant_filter deve adicionar WHERE client_id na query."""
    cid = uuid.uuid4()
    client = _make_client(cid)

    base_query = select(FakeResource)
    filtered = tenant_filter(base_query, FakeResource, client)

    compiled = str(filtered.compile(compile_kwargs={"literal_binds": True}))
    assert "client_id" in compiled


def test_tenant_filter_uses_correct_client_id():
    """O filtro deve usar exatamente o client_id do cliente autenticado."""
    cid = uuid.uuid4()
    client = _make_client(cid)

    query = tenant_filter(select(FakeResource), FakeResource, client)
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))

    # PostgreSQL compila UUIDs sem hífens na literal SQL
    assert str(cid).replace("-", "") in compiled
