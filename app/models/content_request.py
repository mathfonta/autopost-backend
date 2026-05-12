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
    failed = "failed"                 # erro técnico em alguma etapa
    rejected = "rejected"             # rejeitado pelo cliente na revisão


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
    photo_keys: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="Chaves R2 de múltiplas fotos"
    )
    photo_urls: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="URLs presigned de múltiplas fotos"
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

    # ─── Intenção de conteúdo (selecionada pelo cliente antes do upload) ──
    content_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Formato Instagram: feed_photo | carousel | reels | story"
    )
    strategy: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Sub-estratégia: prova_social | antes_depois | hook_choque | enquete | etc."
    )

    # ─── Contexto livre do usuário ───────────────────────────────
    user_context: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Contexto opcional digitado pelo cliente antes do upload (ex: porcelanato, banheiro social)"
    )

    # ─── Variações de legenda (Story 8.3) ───────────────────────
    caption_long: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Variação longa (até 1500 chars)"
    )
    caption_short: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Variação curta (até 300 chars)"
    )
    caption_stories: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Variação Stories (até 150 chars)"
    )
    caption_selected: Mapped[str | None] = mapped_column(
        String(10), nullable=True, server_default="long",
        comment="Variação escolhida: long | short | stories"
    )

    # ─── Edição e retry pelo cliente ────────────────────────────
    caption_edited: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default="false",
        comment="True quando o cliente editou a legenda gerada pelo agente"
    )
    retry_count: Mapped[int] = mapped_column(
        default=0, nullable=False, server_default="0",
        comment="Número de vezes que o cliente pediu nova versão da legenda"
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
