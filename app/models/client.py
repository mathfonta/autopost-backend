"""
Modelo Client — representa um tenant (empresa/profissional) na plataforma.
O id é o UUID do usuário no Supabase Auth (garantia de unicidade multi-tenant).
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(
        String(50), default="starter", nullable=False
    )
    brand_profile: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False, server_default="{}"
    )

    # ─── Meta / Instagram ────────────────────────────────────────
    meta_access_token: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="Long-Lived Token Meta Graph API"
    )
    instagram_business_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Instagram Business Account ID"
    )
    facebook_page_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Facebook Page ID"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Client id={self.id} email={self.email} plan={self.plan}>"
