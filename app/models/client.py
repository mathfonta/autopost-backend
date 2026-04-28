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
    meta_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Expiração do Long-Lived Token Meta"
    )
    instagram_business_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Instagram Business Account ID"
    )
    instagram_username: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Username público do Instagram"
    )
    facebook_page_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Facebook Page ID"
    )
    facebook_page_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Nome da Página do Facebook"
    )

    voice_tone: Mapped[str | None] = mapped_column(
        String(20), nullable=True, server_default="casual",
        comment="Tom de voz do copywriter: formal | casual | technical",
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
