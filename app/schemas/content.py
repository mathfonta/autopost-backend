"""
Schemas Pydantic para os endpoints de ContentRequest.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, field_validator

from app.models.content_request import ContentStatus


# ─── Responses ──────────────────────────────────────────────────

class ContentRequestResponse(BaseModel):
    """Resposta mínima após criação — retornada pelo POST."""
    id: uuid.UUID
    status: ContentStatus
    celery_task_id: str | None = None

    model_config = {"from_attributes": True}


class ContentRequestDetailResponse(BaseModel):
    """Resposta completa — retornada pelo GET /{id}."""
    id: uuid.UUID
    status: ContentStatus
    photo_url: str
    photo_urls: list[str] | None = None
    source_channel: str
    celery_task_id: str | None = None
    error_message: str | None = None
    analysis_result: dict[str, Any] | None = None
    copy_result: dict[str, Any] | None = None
    design_result: dict[str, Any] | None = None
    publish_result: dict[str, Any] | None = None
    caption_edited: bool = False
    retry_count: int = 0
    content_type: str | None = None
    strategy: str | None = None
    user_context: str | None = None
    caption_long: str | None = None
    caption_short: str | None = None
    caption_stories: str | None = None
    caption_selected: str | None = "long"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatchCaptionRequest(BaseModel):
    """Body do endpoint PATCH /{id} — atualiza legenda e/ou seleciona variação."""
    caption: str | None = None
    caption_selected: Literal["long", "short", "stories"] | None = None

    @field_validator("caption_selected")
    @classmethod
    def caption_selected_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in ("long", "short", "stories"):
            raise ValueError("caption_selected deve ser 'long', 'short' ou 'stories'")
        return v


class ContentRequestListResponse(BaseModel):
    """Resposta paginada — retornada pelo GET /."""
    items: list[ContentRequestDetailResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ApproveResponse(BaseModel):
    """Resposta do endpoint de aprovação."""
    id: uuid.UUID
    status: ContentStatus


class RejectRequest(BaseModel):
    """Body opcional do endpoint de rejeição."""
    reason: str | None = None


class RetryResponse(BaseModel):
    """Resposta do endpoint de retry."""
    id: uuid.UUID
    status: ContentStatus
    retry_count: int
