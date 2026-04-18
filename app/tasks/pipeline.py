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
from datetime import datetime, timezone

from celery import chain
from celery.schedules import crontab
from sqlalchemy import select

from app.tasks import celery_app
from app.models.content_request import ContentRequest, ContentStatus

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────

def _run_sync(coro):
    """Executa uma coroutine dentro de uma task Celery (contexto síncrono)."""
    return asyncio.run(coro)


async def _get_request_with_client(request_id: str) -> dict:
    """Busca ContentRequest + dados relevantes do Client associado."""
    from app.core.database import WorkerSessionLocal
    from app.models.client import Client

    uid = uuid.UUID(request_id)
    async with WorkerSessionLocal() as db:
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
            "design_result": req.design_result or {},
            "publish_result": req.publish_result or {},
            # Credenciais Meta (podem ser None)
            "meta_access_token": (client.meta_access_token or "") if client else "",
            "instagram_business_id": (client.instagram_business_id or "") if client else "",
            "facebook_page_id": (client.facebook_page_id or "") if client else "",
        }


async def _get_request(request_id: str) -> ContentRequest:
    """Busca ContentRequest pelo ID, levanta se não encontrar."""
    from app.core.database import WorkerSessionLocal

    uid = uuid.UUID(request_id)
    async with WorkerSessionLocal() as db:
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
    from app.core.database import WorkerSessionLocal

    uid = uuid.UUID(request_id)
    async with WorkerSessionLocal() as db:
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
            analyze_photo_with_ai(req["photo_url"], req["brand_profile"], req.get("photo_key", ""))
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
    Processa a imagem com Pillow (resize, logo, card ou antes/depois)
    e faz upload do resultado para Cloudflare R2.

    Returns:
        request_id
    """
    from app.agents.designer import process_image

    logger.info(f"[prepare_design] request_id={request_id}")

    try:
        req = _run_sync(_get_request_with_client(request_id))
        design = _run_sync(
            process_image(
                request_id,
                req["photo_url"],
                req["analysis_result"],
                req["brand_profile"],
                req.get("photo_key", ""),
            )
        )

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
    Publica o post aprovado no Instagram Business e Facebook via Meta Graph API.
    Deve ser chamado APENAS após aprovação manual do cliente.

    Returns:
        request_id
    """
    from app.agents.publisher import (
        publish_to_instagram,
        publish_to_facebook,
        build_full_caption,
        MetaAPIError,
    )

    logger.info(f"[publish_post] request_id={request_id}")

    try:
        _run_sync(_update_status(request_id, ContentStatus.publishing))

        req = _run_sync(_get_request_with_client(request_id))

        # URL da imagem processada (fallback para original se Designer não rodou)
        image_url = req["design_result"].get("processed_photo_url") or req["photo_url"]
        full_caption = build_full_caption(req["copy_result"])

        access_token = req["meta_access_token"]
        ig_id = req["instagram_business_id"]
        fb_id = req["facebook_page_id"]

        instagram_post_id = None
        facebook_post_id = None
        permalink = None

        # ── Instagram ──
        if ig_id and access_token:
            try:
                ig = _run_sync(publish_to_instagram(ig_id, access_token, image_url, full_caption))
                instagram_post_id = ig["post_id"]
                permalink = ig["permalink"]
            except MetaAPIError as exc:
                if exc.is_token_expired:
                    error_msg = "Token Meta expirado. Acesse Configurações → Redes Sociais para renovar."
                    _run_sync(_update_status(request_id, ContentStatus.failed, error=error_msg))
                    logger.warning(f"[publish_post] token expirado request_id={request_id}")
                    return request_id
                raise

        # ── Facebook (opcional — falha não cancela Instagram) ──
        if fb_id and access_token:
            try:
                fb = _run_sync(publish_to_facebook(fb_id, access_token, image_url, full_caption))
                facebook_post_id = fb["post_id"]
            except MetaAPIError as exc:
                logger.warning(f"[publish_post] falha no Facebook (ignorada): {exc}")

        publish_result = {
            "instagram_post_id": instagram_post_id,
            "facebook_post_id": facebook_post_id,
            "permalink": permalink,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

        _run_sync(_update_status(
            request_id,
            ContentStatus.published,
            result_field="publish_result",
            result_data=publish_result,
        ))

        # Agenda coleta de métricas 24h depois
        if instagram_post_id:
            collect_metrics.apply_async(args=[request_id], countdown=86400)

        logger.info(f"[publish_post] concluído request_id={request_id} ig={instagram_post_id}")
        return request_id

    except Exception as exc:
        logger.error(f"[publish_post] erro: {exc}")
        _run_sync(_update_status(request_id, ContentStatus.failed, error=str(exc)))
        raise self.retry(exc=exc, countdown=60)


# ─── Task 5: Coletor de Métricas ─────────────────────────────────

@celery_app.task(bind=True, name="pipeline.collect_metrics", max_retries=2)
def collect_metrics(self, request_id: str) -> str:
    """
    Coleta métricas do post (impressões, alcance, curtidas, comentários)
    24h após a publicação.

    Agendado automaticamente por publish_post via apply_async(countdown=86400).

    Returns:
        request_id
    """
    from app.agents.publisher import collect_post_metrics

    logger.info(f"[collect_metrics] request_id={request_id}")

    try:
        req = _run_sync(_get_request_with_client(request_id))
        publish_result = req.get("publish_result") or {}
        instagram_post_id = publish_result.get("instagram_post_id")
        access_token = req["meta_access_token"]

        if not instagram_post_id or not access_token:
            logger.info(f"[collect_metrics] sem dados para coletar request_id={request_id}")
            return request_id

        metrics = _run_sync(collect_post_metrics(instagram_post_id, access_token))

        # Atualiza publish_result adicionando métricas
        updated_result = {**publish_result, "metrics": metrics}
        _run_sync(_update_status(
            request_id,
            ContentStatus.published,  # mantém published
            result_field="publish_result",
            result_data=updated_result,
        ))

        # Escreve resultado no cérebro local (falha silenciosa — não quebra o pipeline)
        from app.cerebro.writer import write_post_to_history
        write_post_to_history(req, metrics)

        logger.info(f"[collect_metrics] concluído request_id={request_id}")
        return request_id

    except Exception as exc:
        logger.error(f"[collect_metrics] erro: {exc}")
        raise self.retry(exc=exc, countdown=3600)  # retry em 1h


# ─── Task 6: Atualização do Cérebro (Celery Beat) ────────────────

@celery_app.task(bind=True, name="pipeline.update_cerebro_patterns", max_retries=1)
def update_cerebro_patterns(self) -> str:
    """
    Analisa histórico acumulado e atualiza PADROES.md e INSIGHTS.md.
    Agendado pelo Celery Beat toda segunda-feira às 08:00 (America/Sao_Paulo).
    """
    from app.cerebro.analyzer import analyze_and_update_patterns

    logger.info("[update_cerebro_patterns] iniciando análise semanal do cérebro")

    try:
        _run_sync(analyze_and_update_patterns())
        logger.info("[update_cerebro_patterns] concluído")
        return "ok"
    except Exception as exc:
        logger.error(f"[update_cerebro_patterns] erro: {exc}")
        raise self.retry(exc=exc, countdown=3600)  # retry em 1h


# ─── Task 7: Promoção Global (Celery Beat mensal) ────────────────

@celery_app.task(bind=True, name="pipeline.promote_to_global_cerebro", max_retries=1)
def promote_to_global_cerebro(self) -> str:
    """
    Promove padrões do cérebro local para o global.
    Agendado pelo Celery Beat na primeira segunda de cada mês às 09:00.
    """
    from app.cerebro.promoter import promote_to_global

    logger.info("[promote_to_global_cerebro] iniciando promoção mensal")

    try:
        _run_sync(promote_to_global(project_name="autopost", segment="construção civil"))
        logger.info("[promote_to_global_cerebro] concluído")
        return "ok"
    except Exception as exc:
        logger.error(f"[promote_to_global_cerebro] erro: {exc}")
        raise self.retry(exc=exc, countdown=3600)  # retry em 1h


# ─── Beat Schedule ───────────────────────────────────────────────

celery_app.conf.beat_schedule = {
    "update-cerebro-patterns": {
        "task": "pipeline.update_cerebro_patterns",
        "schedule": crontab(hour=8, minute=0, day_of_week=1),  # toda segunda 08:00
    },
    "promote-to-global-cerebro": {
        "task": "pipeline.promote_to_global_cerebro",
        "schedule": crontab(hour=9, minute=0, day_of_week=1, day_of_month="1-7"),  # 1ª segunda do mês 09:00
    },
}


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
