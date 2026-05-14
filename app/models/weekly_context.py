"""
WeeklyContext — inteligência de mercado semanal gerada via Exa Search (Story 13.4).

Gerado toda segunda às 07:00 (Celery Beat) e exibido no card do dashboard.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import String, Date, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class WeeklyContext(Base):
    __tablename__ = "weekly_context"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    week_of: Mapped[date] = mapped_column(
        Date, nullable=False, index=True,
        comment="Segunda-feira da semana de referência"
    )
    segment: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Segmento de mercado (ex: Construção civil)"
    )
    raw_snippets: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
        comment="Snippets brutos retornados pelo Exa"
    )
    summary: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Resumo em bullet points gerado pelo Gemini"
    )
    hashtags: Mapped[list | None] = mapped_column(
        JSONB, nullable=True,
        comment="Hashtags em alta extraídas dos snippets"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
