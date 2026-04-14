"""
Pipeline de agentes — tasks Celery.

Cada task atualiza o status da ContentRequest e passa para a próxima.
A lógica de IA real é implementada no Epic 2 (app/agents/).

Fluxo:
  analyze_photo → generate_copy → prepare_design
  (aprovação manual pelo cliente)
  publish_post
"""

import asyncio
import logging
import uuid

from celery import chain
from sqlalchemy import select

from app.tasks import celery_app
from app.models.content_request import ContentRequest, ContentStatus

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────

def _run_sync(coro):
    """Executa uma coroutine dentro de uma task Celery (contexto síncrono)."""
    return asyncio.run(coro)


async def _get_request_with_client(request_id: str) -> dict:
    """Busca ContentRequest + brand_profile do Client associado."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    uid = uuid.UUID(request_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ContentRequest).where(ContentRequest.id == uid)
        )
        req = result.scalar_one_or_none()
        if not req:
            raise ValueError(f"ContentRequest {request_id} não encontrado")

        client_result = await db.execute(
            select(Client).where(Client.id == req.client_id)
        )
        client = client_result.scalar_one_or_none()
        brand_profile = client.brand_profile if client else {}

        return {
            "id": str(req.id),
            "photo_url": req.photo_url,
            "photo_key": req.photo_key,
            "brand_profile": brand_profile or {},
            "analysis_result": req.analysis_result or {},
            "copy_result": req.copy_result or {},
        }


async def _get_request(request_id: str) -> ContentRequest:
    """Busca ContentRequest pelo ID, levanta se não encontrar."""
    from app.core.database import AsyncSessionLocal

    uid = uuid.UUID(request_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ContentRequest).where(ContentRequest.id == uid)
        )
        req = result.scalar_one_or_none()
        if not req:
            raise ValueError(f"ContentRequest {request_id} não encontrado")
        return req


async def _update_status(
    request_id: str,
    status: ContentStatus,
    *,
    result_field: str | None = None,
    result_data: dict | None = None,
    error: str | None = None,
    celery_task_id: str | None = None,
) -> None:
    """Atualiza status (e opcionalmente um campo de resultado) da ContentRequest."""
    from app.core.database import AsyncSessionLocal

    uid = uuid.UUID(request_id)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ContentRequest).where(ContentRequest.id == uid)
        )
        req = result.scalar_one_or_none()
        if not req:
            raise ValueError(f"ContentRequest {request_id} não encontrado")

        req.status = status
        if error:
            req.error_message = error
        if celery_task_id:
            req.celery_task_id = celery_task_id
        if result_field and result_data is not None:
            setattr(req, result_field, result_data)

        await db.commit()


# ─── Task 1: Analista de Foto ────────────────────────────────────

@celery_app.task(bind=True, name="pipeline.analyze_photo", max_retries=2)
def analyze_photo(self, request_id: str) -> str:
    """
    Analisa a foto recebida via Claude Haiku com visão.
    Atualiza analysis_result com: quality, content_type, description, publish_clean.

    Returns:
        request_id — passado para a próxima task na chain.
    """
    from app.agents.analyst import analyze_photo_with_ai

    logger.info(f"[analyze_photo] request_id={request_id}")

    try:
        _run_sync(_update_status(
            request_id,
            ContentStatus.analyzing,
            celery_task_id=self.request.id,
        ))

        # Busca foto e brand_profile do cliente
        req = _run_sync(_get_request_with_client(request_id))
        analysis = _run_sync(
            analyze_photo_with_ai(req["photo_url"], req["brand_profile"])
        )

        # Foto ruim → falha com mensagem amigável
        if analysis.get("quality") == "bad":
            error_msg = analysis.get(
                "error_message",
                "A foto não está adequada para publicação. Tente tirar uma nova foto."
            )
            _run_sync(_update_status(
                request_id,
                ContentStatus.failed,
                result_field="analysis_result",
                result_data=analysis,
                error=error_msg,
            ))
            logger.info(f"[analyze_photo] foto reprovada request_id={request_id}")
            return request_id

        # Foto ok → avança para copy
        _run_sync(_update_status(
            request_id,
            ContentStatus.copy,
            result_field="analysis_result",
            result_data=analysis,
        ))

        logger.info(f"[analyze_photo] concluído request_id={request_id}")
        return request_id

    except Exception as exc:
        logger.error(f"[analyze_photo] erro: {exc}")
        _run_sync(_update_status(request_id, ContentStatus.failed, error=str(exc)))
        raise self.retry(exc=exc, countdown=30)


# ─── Task 2: Copywriter ──────────────────────────────────────────

@celery_app.task(bind=True, name="pipeline.generate_copy", max_retries=2)
def generate_copy(self, request_id: str) -> str:
    """
    Gera legenda, hashtags e CTA via Claude Sonnet.
    Usa analysis_result + brand_profile do cliente.

    Returns:
        request_id
    """
    from app.agents.copywriter import generate_copy_with_ai

    logger.info(f"[generate_copy] request_id={request_id}")

    try:
        req = _run_sync(_get_request_with_client(request_id))
        copy = _run_sync(
            generate_copy_with_ai(req["analysis_result"], req["brand_profile"])
        )

        _run_sync(_update_status(
            request_id,
            ContentStatus.design,
            result_field="copy_result",
            result_data=copy,
        ))

        logger.info(f"[generate_copy] concluído request_id={request_id}")
        return request_id

    except Exception as exc:
        logger.error(f"[generate_copy] erro: {exc}")
        _run_sync(_update_status(request_id, ContentStatus.failed, error=str(exc)))
        raise self.retry(exc=exc, countdown=30)


# ─── Task 3: Designer ────────────────────────────────────────────

@celery_app.task(bind=True, name="pipeline.prepare_design", max_retries=2)
def prepare_design(self, request_id: str) -> str:
    """
    Decide o tratamento visual do post.
    Foto de obra → publica limpa. Outros → cria card clean.
    Stub — lógica visual implementada no Epic 2 (app/agents/designer.py).

    Returns:
        request_id
    """
    logger.info(f"[prepare_design] request_id={request_id}")

    try:
        req = _run_sync(_get_request(request_id))
        analysis = req.analysis_result or {}
        publish_clean = analysis.get("publish_clean", True)

        # ── STUB: substituído pelo Designer no Epic 2 ──
        design = {
            "type": "clean_photo" if publish_clean else "card",
            "add_logo": True,
            "overlay_text": False,
            "note": "Design real pendente (Epic 2)",
        }
        # ───────────────────────────────────────────────

        _run_sync(_update_status(
            request_id,
            ContentStatus.awaiting_approval,
            result_field="design_result",
            result_data=design,
        ))

        logger.info(f"[prepare_design] concluído request_id={request_id}")
        return request_id

    except Exception as exc:
        logger.error(f"[prepare_design] erro: {exc}")
        _run_sync(_update_status(request_id, ContentStatus.failed, error=str(exc)))
        raise self.retry(exc=exc, countdown=30)


# ─── Task 4: Publicador ──────────────────────────────────────────

@celery_app.task(bind=True, name="pipeline.publish_post", max_retries=3)
def publish_post(self, request_id: str) -> str:
    """
    Publica o post aprovado no Instagram/Facebook via Meta Graph API.
    Stub — integração Meta implementada no Epic 2 (app/agents/publisher.py).

    Deve ser chamado APENAS após aprovação manual do cliente.
    Returns:
        request_id
    """
    logger.info(f"[publish_post] request_id={request_id}")

    try:
        _run_sync(_update_status(request_id, ContentStatus.publishing))

        # ── STUB: substituído pelo Publicador no Epic 2 ──
        publish_result = {
            "instagram_post_id": None,
            "facebook_post_id": None,
            "permalink": None,
            "note": "Publicação real pendente (Epic 2)",
        }
        # ─────────────────────────────────────────────────

        _run_sync(_update_status(
            request_id,
            ContentStatus.published,
        ))

        logger.info(f"[publish_post] concluído request_id={request_id}")
        return request_id

    except Exception as exc:
        logger.error(f"[publish_post] erro: {exc}")
        _run_sync(_update_status(request_id, ContentStatus.failed, error=str(exc)))
        raise self.retry(exc=exc, countdown=60)


# ─── Pipeline Chain ──────────────────────────────────────────────

def start_content_pipeline(request_id: str):
    """
    Inicia o pipeline Analista → Copywriter → Designer.
    Publicação é disparada separadamente após aprovação do cliente.

    Uso:
        start_content_pipeline(str(content_request.id))
    """
    pipeline = chain(
        analyze_photo.s(request_id),
        generate_copy.s(),
        prepare_design.s(),
    )
    result = pipeline.apply_async()
    logger.info(f"[pipeline] iniciado request_id={request_id} task_id={result.id}")
    return result.id
