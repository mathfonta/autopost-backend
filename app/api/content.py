"""
Endpoints de conteúdo — submissão de foto, histórico, consulta de status.

POST /content-requests          — envia foto, dispara pipeline
GET  /content-requests          — lista histórico paginado
GET  /content-requests/{id}     — detalhe de um request
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone
from math import ceil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_client
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.storage import upload_to_r2, generate_presigned_url
from app.models.client import Client
from app.models.content_request import ContentRequest, ContentStatus
from app.tasks.pipeline import start_content_pipeline, publish_post, retry_generate_copy
from app.tasks.pipeline_autonomous import start_autonomous_pipeline
from app.schemas.content import (
    ApproveResponse,
    ContentRequestDetailResponse,
    ContentRequestListResponse,
    ContentRequestResponse,
    PatchCaptionRequest,
    RejectRequest,
    RetryResponse,
    ScheduleRequest,
    ScheduleResponse,
)

# Limite de quanto no futuro um post pode ser agendado (Story 19.1, AC5)
MAX_SCHEDULE_DAYS = 30

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content-requests", tags=["content"])

# ─── Constantes ─────────────────────────────────────────────────

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime"}
ALLOWED_CONTENT_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES
MAX_FILE_SIZE       = 20  * 1024 * 1024  # 20 MB  — fotos
MAX_VIDEO_FILE_SIZE = 500 * 1024 * 1024  # 500 MB — vídeos (comprimidos internamente)
PRESIGNED_URL_TTL = 3600  # 1 hora

VALID_CONTENT_TYPES = {
    # Formatos Instagram (v2 — genérico)
    "feed_photo", "carousel", "reels", "story",
    # Tipos legados de conteúdo (retrocompatibilidade)
    "post_simples", "obra_andamento", "obra_concluida", "engajamento", "bastidores",
    # Tipos especiais multi-foto
    "before_after",
    # Carrossel autônomo (Epic 17 — sem upload de foto)
    "autonomous_carousel",
}
MULTI_PHOTO_TYPES = {"before_after", "carousel"}


def _freshen_urls(req: ContentRequest) -> ContentRequest:
    """Substitui URLs do R2 por presigned URLs válidas por 1h."""
    try:
        req.photo_url = generate_presigned_url(req.photo_key, PRESIGNED_URL_TTL)
    except Exception:
        pass

    if req.photo_keys:
        fresh = []
        for key in req.photo_keys:
            try:
                fresh.append(generate_presigned_url(key, PRESIGNED_URL_TTL))
            except Exception:
                fresh.append(req.photo_url)
        req.photo_urls = fresh

    if req.design_result and req.design_result.get("r2_key"):
        # Vídeos (reels/story) não geram processed_photo_url — usam thumbnail_url (abaixo)
        if req.design_result.get("type") != "video":
            try:
                fresh = generate_presigned_url(req.design_result["r2_key"], PRESIGNED_URL_TTL)
                req.design_result = {**req.design_result, "processed_photo_url": fresh}
            except Exception:
                pass

    if req.design_result and req.design_result.get("thumbnail_key"):
        try:
            fresh_thumb = generate_presigned_url(req.design_result["thumbnail_key"], PRESIGNED_URL_TTL)
            req.design_result = {**req.design_result, "thumbnail_url": fresh_thumb}
        except Exception:
            pass

    return req


# ─── POST /content-requests ─────────────────────────────────────

@router.post("", response_model=ContentRequestResponse, status_code=201)
@limiter.limit("10/hour")
async def submit_photo(
    request: Request,
    photo: UploadFile | None = File(None),
    photos: list[UploadFile] | None = File(None),
    content_type: str | None = Form(None),
    strategy: str | None = Form(None),
    user_context: str | None = Form(None),
    marketing_intent: str | None = Form(None),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Recebe uma ou mais fotos, faz upload para R2 e dispara o pipeline.
    Campo `photo` é mantido para retrocompatibilidade.
    """
    from app.tasks.pipeline import start_content_pipeline

    # ── Normaliza para effective_photos ──
    if photos:
        effective_photos = photos
    elif photo:
        effective_photos = [photo]
    else:
        raise HTTPException(status_code=422, detail="Ao menos uma foto é obrigatória.")

    # ── Valida content_type ──
    if content_type and content_type not in VALID_CONTENT_TYPES:
        raise HTTPException(status_code=422, detail=f"content_type inválido: {content_type}")

    # ── Valida contagem por tipo ──
    n = len(effective_photos)
    if content_type == "before_after" and n != 2:
        raise HTTPException(status_code=422, detail="before_after requer exatamente 2 fotos.")
    if content_type == "carousel" and not (2 <= n <= 10):
        raise HTTPException(status_code=422, detail="carousel requer 2–10 fotos.")
    if content_type == "reels":
        if n != 1 or (effective_photos[0].content_type or "") not in ALLOWED_VIDEO_TYPES:
            raise HTTPException(status_code=422, detail="reels requer 1 arquivo de vídeo (.mp4 ou .mov).")
    if content_type == "story" and n != 1:
        raise HTTPException(status_code=422, detail="story requer exatamente 1 arquivo.")
    if content_type and content_type not in MULTI_PHOTO_TYPES and content_type not in {"reels", "story"} and n != 1:
        raise HTTPException(status_code=422, detail="Tipos simples aceitam apenas 1 foto.")
    if n > 10:
        raise HTTPException(status_code=422, detail="Máximo de 10 fotos por upload.")

    # ── Upload para R2 ──
    keys: list[str] = []
    urls: list[str] = []

    for i, upload in enumerate(effective_photos):
        photo_content_type = upload.content_type or ""
        if photo_content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Foto {i + 1}: formato inválido ({photo_content_type}). Use JPEG, PNG, WEBP, MP4 ou MOV.",
            )

        data = await upload.read()
        is_video = photo_content_type in ALLOWED_VIDEO_TYPES
        size_limit = MAX_VIDEO_FILE_SIZE if is_video else MAX_FILE_SIZE
        size_label = "500MB" if is_video else "20MB"
        if len(data) > size_limit:
            raise HTTPException(
                status_code=422,
                detail=f"Arquivo {i + 1}: muito grande ({len(data) // (1024 * 1024)}MB). Máximo: {size_label}.",
            )

        if is_video:
            from app.core.video import compress_video
            data = compress_video(data, content_type=photo_content_type)

        ext = ".mp4" if is_video else ".jpg"
        key = f"uploads/{current_client.id}/{uuid.uuid4()}{ext}"
        try:
            url = await upload_to_r2(key, data, photo_content_type)
        except Exception as exc:
            logger.error(f"[content] falha no upload R2 foto {i + 1}: {exc}")
            raise HTTPException(status_code=503, detail="Serviço de armazenamento indisponível. Tente novamente.")

        keys.append(key)
        urls.append(url)

    # ── Cria ContentRequest ──
    req = ContentRequest(
        id=uuid.uuid4(),
        client_id=current_client.id,
        photo_key=keys[0],
        photo_url=urls[0],
        photo_keys=keys,
        photo_urls=urls,
        source_channel="app",
        status=ContentStatus.pending,
        content_type=content_type,
        strategy=strategy or None,
        user_context=user_context or None,
        marketing_intent=marketing_intent or None,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    # ── Dispara pipeline (fire-and-forget) ──
    task_id = start_content_pipeline(str(req.id))
    req.celery_task_id = task_id
    await db.commit()
    await db.refresh(req)

    logger.info(f"[content] request criado id={req.id} n_photos={n} task_id={task_id}")
    return req


# ─── POST /content-requests/autonomous ─────────────────────────

class AutonomousCarouselCreate(BaseModel):
    theme_id: str
    marketing_intent: str | None = None


@router.post("/autonomous", response_model=ContentRequestResponse, status_code=201)
@limiter.limit("5/hour")
async def create_autonomous_carousel(
    request: Request,
    body: AutonomousCarouselCreate,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Cria um carrossel autônomo baseado em tema da biblioteca.
    Não requer upload de foto — o pipeline gera as imagens.
    """
    from app.data.theme_library import THEME_LIBRARY
    all_themes = {t["id"]: t for themes in THEME_LIBRARY.values() for t in themes}
    if body.theme_id not in all_themes:
        raise HTTPException(status_code=422, detail=f"Tema '{body.theme_id}' não encontrado.")

    req = ContentRequest(
        id=uuid.uuid4(),
        client_id=current_client.id,
        photo_key="",
        photo_url="",
        photo_keys=[],
        photo_urls=[],
        source_channel="app",
        status=ContentStatus.pending,
        content_type="autonomous_carousel",
        theme_id=body.theme_id,
        marketing_intent=body.marketing_intent or None,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    task_id = start_autonomous_pipeline(str(req.id))
    req.celery_task_id = task_id
    await db.commit()
    await db.refresh(req)

    logger.info(f"[content] carrossel autônomo criado id={req.id} theme_id={body.theme_id}")
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
    status: str | None = Query(None, description="Filtra por status (ex.: 'scheduled')"),
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Lista paginada dos ContentRequests do cliente autenticado.

    Sem `status`: ordena por criação (mais recentes primeiro) — comportamento
    original. Com `status=scheduled` (Epic 19, Story 19.5): ordena por
    `scheduled_for` crescente (próximo a publicar primeiro) — a ordem por
    `created_at` não faz sentido para a fila de agendados.
    """
    status_filter: ContentStatus | None = None
    if status:
        try:
            status_filter = ContentStatus(status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"status inválido: {status!r}")

    offset = (page - 1) * page_size
    filters = [ContentRequest.client_id == current_client.id]
    if status_filter:
        filters.append(ContentRequest.status == status_filter)

    order_by = (
        ContentRequest.scheduled_for.asc()
        if status_filter == ContentStatus.scheduled
        else ContentRequest.created_at.desc()
    )

    # Total
    count_result = await db.execute(select(func.count()).where(*filters))
    total = count_result.scalar_one()

    # Items
    items_result = await db.execute(
        select(ContentRequest)
        .where(*filters)
        .order_by(order_by)
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


# ─── PATCH /content-requests/{id} ──────────────────────────────

@router.patch("/{request_id}", response_model=ContentRequestDetailResponse)
async def patch_caption(
    request_id: uuid.UUID,
    body: PatchCaptionRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Atualiza a legenda de um post aguardando aprovação.
    Só permitido quando status == awaiting_approval.
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
            detail=f"Legenda só pode ser editada quando status é awaiting_approval. Status atual: {req.status.value}.",
        )

    copy_result = dict(req.copy_result or {})

    if body.caption_selected is not None:
        req.caption_selected = body.caption_selected
        variant_map = {
            "long": req.caption_long,
            "short": req.caption_short,
            "stories": req.caption_stories,
        }
        selected_text = variant_map.get(body.caption_selected)
        if selected_text:
            copy_result["caption"] = selected_text

    if body.caption is not None:
        copy_result["caption"] = body.caption
        req.caption_edited = True

    req.copy_result = copy_result
    await db.commit()
    await db.refresh(req)

    logger.info(f"[content] legenda atualizada id={req.id} caption_selected={req.caption_selected}")
    return _freshen_urls(req)


# ─── POST /content-requests/{id}/retry ─────────────────────────

RETRY_MAX = 3


@router.post("/{request_id}/retry", response_model=RetryResponse)
async def retry_content_request(
    request_id: uuid.UUID,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Regera a legenda do post sem reiniciar o fluxo completo.
    Só permitido quando status == awaiting_approval e retry_count < 3.
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
            detail=f"Retry só permitido quando status é awaiting_approval. Status atual: {req.status.value}.",
        )

    if req.retry_count >= RETRY_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"Máximo de {RETRY_MAX} tentativas atingido.",
        )

    req.retry_count += 1
    req.status = ContentStatus.copy
    await db.commit()

    retry_generate_copy.delay(str(req.id))

    logger.info(f"[content] retry disparado id={req.id} retry_count={req.retry_count}")
    return RetryResponse(id=req.id, status=ContentStatus.copy, retry_count=req.retry_count)


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


def _validate_scheduled_for(scheduled_for: datetime) -> datetime:
    """
    Normaliza e valida um horário de agendamento: timezone-aware (assume
    UTC se naive), no futuro, e dentro da janela de MAX_SCHEDULE_DAYS.
    Compartilhado entre agendar (Story 19.1) e reagendar (Story 19.2).
    """
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    if scheduled_for <= now:
        raise HTTPException(status_code=422, detail="scheduled_for precisa ser no futuro.")
    if scheduled_for > now + timedelta(days=MAX_SCHEDULE_DAYS):
        raise HTTPException(
            status_code=422,
            detail=f"scheduled_for não pode passar de {MAX_SCHEDULE_DAYS} dias no futuro.",
        )
    return scheduled_for


# ─── POST /content-requests/{id}/schedule ────────────────────────
# Epic 19 (Agendamento Inteligente) — Story 19.1.
# Endpoint separado do /approve por decisão de arquitetura (ver
# docs/stories/epic-19-agendamento/epic.md, Architecture Review):
# intenções e respostas distintas, zero risco de regressão no
# caminho "Publicar agora".

@router.post("/{request_id}/schedule", response_model=ScheduleResponse)
async def schedule_content_request(
    request_id: uuid.UUID,
    body: ScheduleRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Agenda um post aguardando aprovação para publicação automática num
    horário futuro. NÃO dispara publish_post — quem publica no horário
    marcado é o executor Celery Beat (Story 19.2, pipeline.publish_scheduled_posts).
    Apenas requests com status `awaiting_approval` podem ser agendados.
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
            detail=f"Este request não pode ser agendado. Status atual: {req.status.value}.",
        )

    scheduled_for = _validate_scheduled_for(body.scheduled_for)

    req.status = ContentStatus.scheduled
    req.scheduled_for = scheduled_for
    await db.commit()

    logger.info(f"[content] agendado id={req.id} scheduled_for={scheduled_for.isoformat()}")
    return ScheduleResponse(id=req.id, status=ContentStatus.scheduled, scheduled_for=scheduled_for)


# ─── POST /content-requests/{id}/schedule/cancel ─────────────────
# Story 19.2. Devolve para awaiting_approval — decisão travada no
# Architecture Review: o conteúdo já foi aprovado pelo cliente,
# cancelar o agendamento não deve descartá-lo (isso é o /reject).

@router.post("/{request_id}/schedule/cancel", response_model=ApproveResponse)
async def cancel_scheduled_content_request(
    request_id: uuid.UUID,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Cancela o agendamento de um post — volta para awaiting_approval."""
    result = await db.execute(
        select(ContentRequest).where(ContentRequest.id == request_id)
    )
    req = result.scalar_one_or_none()

    if not req:
        raise HTTPException(status_code=404, detail="Request não encontrado.")

    if req.client_id != current_client.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    if req.status != ContentStatus.scheduled:
        raise HTTPException(
            status_code=409,
            detail=f"Este request não está agendado. Status atual: {req.status.value}.",
        )

    req.status = ContentStatus.awaiting_approval
    req.scheduled_for = None
    await db.commit()

    logger.info(f"[content] agendamento cancelado id={req.id}")
    return ApproveResponse(id=req.id, status=ContentStatus.awaiting_approval)


# ─── PATCH /content-requests/{id}/schedule ───────────────────────
# Story 19.2 — reagendar: atualiza scheduled_for mantendo status=scheduled.

@router.patch("/{request_id}/schedule", response_model=ScheduleResponse)
async def reschedule_content_request(
    request_id: uuid.UUID,
    body: ScheduleRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Reagenda um post já agendado para um novo horário."""
    result = await db.execute(
        select(ContentRequest).where(ContentRequest.id == request_id)
    )
    req = result.scalar_one_or_none()

    if not req:
        raise HTTPException(status_code=404, detail="Request não encontrado.")

    if req.client_id != current_client.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    if req.status != ContentStatus.scheduled:
        raise HTTPException(
            status_code=409,
            detail=f"Este request não está agendado. Status atual: {req.status.value}.",
        )

    scheduled_for = _validate_scheduled_for(body.scheduled_for)
    req.scheduled_for = scheduled_for
    await db.commit()

    logger.info(f"[content] reagendado id={req.id} scheduled_for={scheduled_for.isoformat()}")
    return ScheduleResponse(id=req.id, status=ContentStatus.scheduled, scheduled_for=scheduled_for)


# ─── DELETE /content-requests/{id} ─────────────────────────────

DELETABLE_STATUSES = {ContentStatus.failed, ContentStatus.rejected}


@router.delete("/{request_id}", status_code=204)
async def delete_content_request(
    request_id: uuid.UUID,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove permanentemente um post com status 'failed' ou 'rejected'.
    Posts publicados ou em processamento não podem ser excluídos.
    """
    result = await db.execute(
        select(ContentRequest).where(ContentRequest.id == request_id)
    )
    req = result.scalar_one_or_none()

    if not req:
        raise HTTPException(status_code=404, detail="Request não encontrado.")

    if req.client_id != current_client.id:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    if req.status not in DELETABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Apenas posts com status 'failed' ou 'rejected' podem ser excluídos. Status atual: {req.status.value}.",
        )

    await db.delete(req)
    await db.commit()
    logger.info(f"[content] excluído id={req.id} status={req.status.value}")


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
    req.status = ContentStatus.rejected
    req.error_message = reason or "Rejeitado pelo cliente"
    await db.commit()

    logger.info(f"[content] rejeitado id={req.id}")
    return ApproveResponse(id=req.id, status=ContentStatus.rejected)
