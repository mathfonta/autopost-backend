"""
Endpoints de conteúdo — submissão de foto, histórico, consulta de status.

POST /content-requests          — envia foto, dispara pipeline
GET  /content-requests          — lista histórico paginado
GET  /content-requests/{id}     — detalhe de um request
"""

import uuid
import logging
from math import ceil

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_client
from app.core.database import get_db
from app.core.storage import upload_to_r2, generate_presigned_url
from app.models.client import Client
from app.models.content_request import ContentRequest, ContentStatus
from app.tasks.pipeline import start_content_pipeline, publish_post
from app.schemas.content import (
    ApproveResponse,
    ContentRequestDetailResponse,
    ContentRequestListResponse,
    ContentRequestResponse,
    RejectRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content-requests", tags=["content"])

# ─── Constantes ─────────────────────────────────────────────────

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
PRESIGNED_URL_TTL = 3600  # 1 hora


def _freshen_urls(req: ContentRequest) -> ContentRequest:
    """Substitui URLs do R2 por presigned URLs válidas por 1h."""
    try:
        req.photo_url = generate_presigned_url(req.photo_key, PRESIGNED_URL_TTL)
    except Exception:
        pass

    if req.design_result and req.design_result.get("r2_key"):
        try:
            fresh = generate_presigned_url(req.design_result["r2_key"], PRESIGNED_URL_TTL)
            req.design_result = {**req.design_result, "processed_photo_url": fresh}
        except Exception:
            pass

    return req


# ─── POST /content-requests ─────────────────────────────────────

@router.post("", response_model=ContentRequestResponse, status_code=201)
async def submit_photo(
    photo: UploadFile = File(...),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Recebe uma foto, faz upload para R2 e dispara o pipeline de agentes.
    Retorna imediatamente com o ID do request e o celery_task_id.
    """
    from app.tasks.pipeline import start_content_pipeline

    # ── Valida tipo ──
    content_type = photo.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Formato inválido: {content_type}. Use JPEG, PNG ou WEBP.",
        )

    # ── Lê e valida tamanho ──
    data = await photo.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=422,
            detail=f"Arquivo muito grande: {len(data) // (1024*1024)}MB. Máximo: 20MB.",
        )

    # ── Upload para R2 ──
    key = f"uploads/{current_client.id}/{uuid.uuid4()}.jpg"
    try:
        photo_url = await upload_to_r2(key, data, "image/jpeg")
    except Exception as exc:
        logger.error(f"[content] falha no upload R2: {exc}")
        raise HTTPException(status_code=503, detail="Serviço de armazenamento indisponível. Tente novamente.")

    # ── Cria ContentRequest ──
    req = ContentRequest(
        id=uuid.uuid4(),
        client_id=current_client.id,
        photo_key=key,
        photo_url=photo_url,
        source_channel="app",
        status=ContentStatus.pending,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    # ── Dispara pipeline (fire-and-forget) ──
    task_id = start_content_pipeline(str(req.id))
    req.celery_task_id = task_id
    await db.commit()
    await db.refresh(req)

    logger.info(f"[content] request criado id={req.id} task_id={task_id}")
    return req


# ─── GET /content-requests/{id} ─────────────────────────────────

@router.get("/{request_id}", response_model=ContentRequestDetailResponse)
async def get_content_request(
    request_id: uuid.UUID,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Retorna o detalhe de um ContentRequest pelo ID."""
    result = await db.execute(
        select(ContentRequest).where(ContentRequest.id == request_id)
    )
    req = result.scalar_one_or_none()

    if not req:
        raise HTTPException(status_code=404, detail="Request não encontrado.")

    if req.client_id != current_client.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    return _freshen_urls(req)


# ─── GET /content-requests ──────────────────────────────────────

@router.get("", response_model=ContentRequestListResponse)
async def list_content_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Lista paginada dos ContentRequests do cliente autenticado."""
    offset = (page - 1) * page_size

    # Total
    count_result = await db.execute(
        select(func.count()).where(ContentRequest.client_id == current_client.id)
    )
    total = count_result.scalar_one()

    # Items
    items_result = await db.execute(
        select(ContentRequest)
        .where(ContentRequest.client_id == current_client.id)
        .order_by(ContentRequest.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(items_result.scalars().all())

    return ContentRequestListResponse(
        items=[_freshen_urls(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total > 0 else 1,
    )


# ─── POST /content-requests/{id}/approve ────────────────────────

@router.post("/{request_id}/approve", response_model=ApproveResponse)
async def approve_content_request(
    request_id: uuid.UUID,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Aprova um post aguardando aprovação e dispara a publicação.
    Apenas requests com status `awaiting_approval` podem ser aprovados.
    """
    result = await db.execute(
        select(ContentRequest).where(ContentRequest.id == request_id)
    )
    req = result.scalar_one_or_none()

    if not req:
        raise HTTPException(status_code=404, detail="Request não encontrado.")

    if req.client_id != current_client.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    if req.status != ContentStatus.awaiting_approval:
        raise HTTPException(
            status_code=409,
            detail=f"Este request não pode ser aprovado. Status atual: {req.status.value}.",
        )

    req.status = ContentStatus.approved
    await db.commit()

    # Dispara publicação (fire-and-forget)
    publish_post.delay(str(req.id))

    logger.info(f"[content] aprovado id={req.id}")
    return ApproveResponse(id=req.id, status=ContentStatus.publishing)


# ─── POST /content-requests/{id}/reject ─────────────────────────

@router.post("/{request_id}/reject", response_model=ApproveResponse)
async def reject_content_request(
    request_id: uuid.UUID,
    body: RejectRequest | None = None,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Rejeita um post e registra o motivo."""
    result = await db.execute(
        select(ContentRequest).where(ContentRequest.id == request_id)
    )
    req = result.scalar_one_or_none()

    if not req:
        raise HTTPException(status_code=404, detail="Request não encontrado.")

    if req.client_id != current_client.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    reason = body.reason if body and body.reason else None
    req.status = ContentStatus.failed
    req.error_message = f"Rejeitado pelo cliente: {reason}" if reason else "Rejeitado pelo cliente"
    await db.commit()

    logger.info(f"[content] rejeitado id={req.id}")
    return ApproveResponse(id=req.id, status=ContentStatus.failed)
