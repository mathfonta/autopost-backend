"""
Schemas Pydantic para os endpoints de ContentRequest.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

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
    source_channel: str
    celery_task_id: str | None = None
    error_message: str | None = None
    analysis_result: dict[str, Any] | None = None
    copy_result: dict[str, Any] | None = None
    design_result: dict[str, Any] | None = None
    publish_result: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
