"""
Mixins reutilizáveis para modelos SQLAlchemy.
"""

import uuid
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class TenantMixin:
    """
    Adiciona client_id a qualquer tabela multi-tenant.
    Toda tabela que pertence a um tenant deve herdar este mixin.

    O index=True cria automaticamente ix_<tablename>_client_id.

    Uso:
        class Post(Base, TenantMixin):
            __tablename__ = "posts"
            ...
    """

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
