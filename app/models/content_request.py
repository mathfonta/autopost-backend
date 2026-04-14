"""
ContentRequest — representa uma foto entrando no pipeline de agentes.

Estados:
  pending → analyzing → copy → design → awaiting_approval
  → approved → publishing → published
  (qualquer estado pode ir para) → failed
"""

import uuid
import enum
from datetime import datetime

from sqlalchemy import String, DateTime, Enum as SAEnum, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.mixins import TenantMixin


class ContentStatus(str, enum.Enum):
    pending = "pending"               # foto recebida, aguardando processamento
    analyzing = "analyzing"           # Agente Analista rodando
    copy = "copy"                     # Agente Copywriter rodando
    design = "design"                 # Agente Designer rodando
    awaiting_approval = "awaiting_approval"  # aguardando aprovação do cliente
    approved = "approved"             # cliente aprovou
    publishing = "publishing"         # Agente Publicador rodando
    published = "published"           # publicado com sucesso
    failed = "failed"                 # erro em alguma etapa


class ContentRequest(Base, TenantMixin):
    __tablename__ = "content_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ─── Foto ────────────────────────────────────────────────────
    photo_key: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="Chave no Cloudflare R2"
    )
    photo_url: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="URL pública temporária"
    )
    source_channel: Mapped[str] = mapped_column(
        String(50), default="app", nullable=False,
        comment="app | whatsapp | google_drive | dropbox | onedrive"
    )

    # ─── Pipeline ────────────────────────────────────────────────
    status: Mapped[ContentStatus] = mapped_column(
        SAEnum(ContentStatus, name="content_status"),
        default=ContentStatus.pending,
        nullable=False,
        index=True,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ─── Resultados dos agentes (preenchidos conforme pipeline avança) ──
    analysis_result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Output do Agente Analista"
    )
    copy_result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Output do Agente Copywriter"
    )
    design_result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Output do Agente Designer"
    )
    publish_result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Output do Agente Publicador (IDs, permalink, métricas)"
    )

    # ─── Timestamps ──────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
