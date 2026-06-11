"""
Pipeline autônomo — carrossel temático sem upload de foto.
Fluxo: tema → estrutura de slides → renderizar imagens → copy → awaiting_approval
"""
import asyncio
import logging
import uuid

from sqlalchemy import select

from app.tasks import celery_app
from app.models.content_request import ContentRequest, ContentStatus

logger = logging.getLogger(__name__)


def _run_sync(coro):
    return asyncio.run(coro)


@celery_app.task(bind=True, name="pipeline.process_autonomous_carousel", max_retries=2)
def process_autonomous_carousel(self, request_id: str) -> str:
    """
    Pipeline autônomo:
    1. Carrega request (theme_id + brand_profile)
    2. Gera estrutura de slides via Claude
    3. Renderiza imagens com Pillow
    4. Faz upload das imagens para R2
    5. Gera legenda com copywriter
    6. Salva design_result + copy_result → awaiting_approval
    """
    from app.tasks.pipeline import _update_status, _get_request_with_client, _save_caption_variants
    from app.agents.theme_generator import generate_slide_structure
    from app.agents.slide_designer import render_carousel_slides
    from app.agents.copywriter import generate_copy_with_ai
    from app.core.storage import upload_to_r2

    logger.info(f"[autonomous] iniciando request_id={request_id}")

    try:
        _run_sync(_update_status(
            request_id,
            ContentStatus.analyzing,
            celery_task_id=self.request.id,
        ))

        # 1. Carrega request
        req = _run_sync(_get_request_with_client(request_id))
        theme_id = req.get("theme_id")
        if not theme_id:
            raise ValueError("theme_id ausente no ContentRequest")

        brand_profile = req["brand_profile"]
        client_id = req["client_id"]

        # 2. Gera estrutura de slides
        logger.info(f"[autonomous] gerando estrutura theme_id={theme_id}")
        _run_sync(_update_status(request_id, ContentStatus.copy))
        structure = _run_sync(generate_slide_structure(theme_id, brand_profile))

        # 3. Renderiza imagens com Pillow
        logger.info(f"[autonomous] renderizando {len(structure.get('content_slides', [])) + 2} slides")
        _run_sync(_update_status(request_id, ContentStatus.design))
        slides_bytes = _run_sync(render_carousel_slides(structure, brand_profile))

        # 4. Upload para R2
        keys: list[str] = []
        urls: list[str] = []
        for i, png_bytes in enumerate(slides_bytes):
            key = f"autonomous/{client_id}/{request_id}/slide_{i:02d}.png"
            url = _run_sync(upload_to_r2(key, png_bytes, "image/png"))
            keys.append(key)
            urls.append(url)
            logger.info(f"[autonomous] slide {i} upado key={key}")

        # Salva photo_keys/photo_urls no request (para o publisher usar)
        async def _save_photos():
            from app.core.database import WorkerSessionLocal
            uid = uuid.UUID(request_id)
            async with WorkerSessionLocal() as db:
                result = await db.execute(
                    select(ContentRequest).where(ContentRequest.id == uid)
                )
                r = result.scalar_one_or_none()
                if r:
                    r.photo_keys = keys
                    r.photo_urls = urls
                    r.photo_key = keys[0]
                    r.photo_url = urls[0]
                    await db.commit()

        _run_sync(_save_photos())

        # 5. Gera legenda
        logger.info("[autonomous] gerando legenda")
        slide_summary = {
            "theme": theme_id,
            "headline": structure["title_card"]["headline"],
            "content_slides": structure.get("content_slides", []),
            "cta": structure["cta_card"]["headline"],
            "content_type": "carousel",
        }

        copy = _run_sync(generate_copy_with_ai(
            slide_summary,
            brand_profile,
            user_content_type="carousel",
            strategy="passo_a_passo",
            marketing_intent=req.get("marketing_intent"),
        ))

        _run_sync(_save_caption_variants(
            request_id,
            copy.get("caption_long"),
            copy.get("caption_short"),
            copy.get("caption_stories"),
        ))

        # 6. Salva design_result e avança para aprovação
        design_result = {
            "type": "autonomous_carousel",
            "theme_id": theme_id,
            "slide_structure": structure,
            "design_keys": keys,
            "design_urls": urls,
            "r2_key": keys[0],
        }

        _run_sync(_update_status(
            request_id,
            ContentStatus.awaiting_approval,
            result_field="design_result",
            result_data=design_result,
        ))

        # Atualiza copy_result
        async def _save_copy():
            from app.core.database import WorkerSessionLocal
            uid = uuid.UUID(request_id)
            async with WorkerSessionLocal() as db:
                result = await db.execute(
                    select(ContentRequest).where(ContentRequest.id == uid)
                )
                r = result.scalar_one_or_none()
                if r:
                    r.copy_result = copy
                    await db.commit()

        _run_sync(_save_copy())

        # Push notification (falha silenciosa)
        try:
            from app.api.push import send_push_notification
            _run_sync(send_push_notification(
                client_id=client_id,
                title="AutoPost",
                body="Carrossel automático aguardando aprovação!",
                url=f"/posts/{request_id}",
            ))
        except Exception as push_exc:
            logger.warning(f"[autonomous] push falhou (ignorado): {push_exc}")

        logger.info(f"[autonomous] concluído request_id={request_id} slides={len(keys)}")
        return request_id

    except Exception as exc:
        logger.error(f"[autonomous] erro: {exc}")
        _run_sync(_update_status(request_id, ContentStatus.failed, error=str(exc)))
        raise self.retry(exc=exc, countdown=30)


def start_autonomous_pipeline(request_id: str) -> str:
    """Inicia o pipeline autônomo (fire-and-forget)."""
    result = process_autonomous_carousel.delay(request_id)
    logger.info(f"[autonomous] pipeline iniciado request_id={request_id} task_id={result.id}")
    return result.id
