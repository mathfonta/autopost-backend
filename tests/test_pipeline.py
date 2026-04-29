"""
Testes do pipeline Celery — tasks stub + chain + estados.
Não conecta ao Redis nem ao banco — usa mocks.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.content_request import ContentStatus
from app.tasks.pipeline import (
    analyze_photo,
    generate_copy,
    prepare_design,
    publish_post,
    start_content_pipeline,
)
from app.agents.publisher import publish_carousel_to_instagram


# ─── Helpers ────────────────────────────────────────────────────

def _fake_request(status=ContentStatus.pending):
    req = MagicMock()
    req.id = uuid.uuid4()
    req.status = status
    req.analysis_result = None
    req.copy_result = None
    req.design_result = None
    return req


def _rid():
    return str(uuid.uuid4())


# ─── analyze_photo ──────────────────────────────────────────────


def _fake_request_with_client():
    return {
        "id": str(uuid.uuid4()),
        "photo_url": "https://r2.example.com/photo.jpg",
        "photo_key": "uploads/photo.jpg",
        "brand_profile": {"segment": "construção", "city": "Florianópolis"},
        "analysis_result": {},
        "copy_result": {},
        "user_context": None,
    }


def _fake_ai_analysis():
    return {
        "quality": "good",
        "quality_reason": "ok",
        "content_type": "obra_realizada",
        "description": "Foto de obra.",
        "publish_clean": True,
        "stage": "acabamento",
    }


def test_analyze_photo_transitions_to_copy():
    """analyze_photo deve setar status=copy e preencher analysis_result."""
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append((request_id, status, kwargs))

    async def fake_get_with_client(request_id):
        return _fake_request_with_client()

    async def fake_ai(photo_url, brand_profile, photo_key="", user_context=None):
        return _fake_ai_analysis()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get_with_client),
        patch("app.agents.analyst.analyze_photo_with_ai", side_effect=fake_ai),
    ):
        result = analyze_photo.run(rid)

    assert result == rid
    statuses = [c[1] for c in call_log]
    assert ContentStatus.analyzing in statuses
    assert ContentStatus.copy in statuses


def test_analyze_photo_sets_analysis_result():
    """analyze_photo deve preencher analysis_result no segundo _update_status."""
    rid = _rid()
    results = []

    async def fake_update(request_id, status, **kwargs):
        if "result_data" in kwargs:
            results.append(kwargs["result_data"])

    async def fake_get_with_client(request_id):
        return _fake_request_with_client()

    async def fake_ai(photo_url, brand_profile, photo_key="", user_context=None):
        return _fake_ai_analysis()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get_with_client),
        patch("app.agents.analyst.analyze_photo_with_ai", side_effect=fake_ai),
    ):
        analyze_photo.run(rid)

    assert results, "analysis_result não foi gravado"
    assert "quality" in results[0]
    assert "content_type" in results[0]


def test_analyze_photo_marks_failed_on_error():
    """analyze_photo deve marcar failed se ocorrer exceção."""
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)
        if status == ContentStatus.analyzing:
            raise RuntimeError("Banco indisponível")

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        pytest.raises(Exception),
    ):
        analyze_photo.run(rid)

    assert ContentStatus.failed in call_log


# ─── generate_copy ──────────────────────────────────────────────


def _fake_ai_copy():
    return {
        "caption": "Mais um projeto entregue! ✨ Piso em porcelanato 90x90.",
        "hashtags": ["construcaocivil", "florianopolis", "porcelanato"],
        "cta": "Entre em contato pelo link na bio!",
        "suggested_time": "18:00",
    }


def test_generate_copy_transitions_to_design():
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    async def fake_get_with_client(request_id):
        return _fake_request_with_client()

    async def fake_ai(analysis_result, brand_profile, **kwargs):
        return _fake_ai_copy()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get_with_client),
        patch("app.tasks.pipeline._save_caption_variants", new_callable=AsyncMock),
        patch("app.agents.copywriter.generate_copy_with_ai", side_effect=fake_ai),
    ):
        result = generate_copy.run(rid)

    assert result == rid
    assert ContentStatus.design in call_log


def test_generate_copy_sets_copy_result():
    rid = _rid()
    results = []

    async def fake_update(request_id, status, **kwargs):
        if "result_data" in kwargs:
            results.append(kwargs["result_data"])

    async def fake_get_with_client(request_id):
        return _fake_request_with_client()

    async def fake_ai(analysis_result, brand_profile, **kwargs):
        return _fake_ai_copy()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get_with_client),
        patch("app.tasks.pipeline._save_caption_variants", new_callable=AsyncMock),
        patch("app.agents.copywriter.generate_copy_with_ai", side_effect=fake_ai),
    ):
        generate_copy.run(rid)

    assert results
    copy = results[0]
    assert "caption" in copy
    assert "hashtags" in copy
    assert "cta" in copy


# ─── prepare_design ─────────────────────────────────────────────


def _fake_ai_design():
    return {
        "processed_photo_url": "https://r2.example.com/processed/test/final.jpg",
        "type": "clean_photo",
        "dimensions": "1080x1080",
        "file_size_kb": 280,
        "r2_key": "processed/test/final.jpg",
    }


def test_prepare_design_transitions_to_awaiting_approval():
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    async def fake_get_with_client(request_id):
        return _fake_request_with_client()

    async def fake_ai(request_id, photo_url, analysis_result, brand_profile, photo_key=""):
        return _fake_ai_design()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get_with_client),
        patch("app.agents.designer.process_image", side_effect=fake_ai),
    ):
        result = prepare_design.run(rid)

    assert result == rid
    assert ContentStatus.awaiting_approval in call_log


def test_prepare_design_clean_photo_type():
    """publish_clean=True → design.type == clean_photo."""
    rid = _rid()
    results = []

    async def fake_update(request_id, status, **kwargs):
        if "result_data" in kwargs:
            results.append(kwargs["result_data"])

    async def fake_get_with_client(request_id):
        return _fake_request_with_client()

    async def fake_ai(request_id, photo_url, analysis_result, brand_profile, photo_key=""):
        return _fake_ai_design()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get_with_client),
        patch("app.agents.designer.process_image", side_effect=fake_ai),
    ):
        prepare_design.run(rid)

    assert results
    assert results[0]["type"] == "clean_photo"


def test_prepare_design_card_type():
    """publish_clean=False → design.type == card (via mock)."""
    rid = _rid()
    results = []

    async def fake_update(request_id, status, **kwargs):
        if "result_data" in kwargs:
            results.append(kwargs["result_data"])

    async def fake_get_with_client(request_id):
        return _fake_request_with_client()

    async def fake_ai(request_id, photo_url, analysis_result, brand_profile, photo_key=""):
        return {**_fake_ai_design(), "type": "card"}

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get_with_client),
        patch("app.agents.designer.process_image", side_effect=fake_ai),
    ):
        prepare_design.run(rid)

    assert results
    assert results[0]["type"] == "card"


# ─── publish_post ───────────────────────────────────────────────


def _fake_request_with_meta():
    return {
        **_fake_request_with_client(),
        "design_result": {"processed_photo_url": "https://r2.example.com/processed/test/final.jpg"},
        "copy_result": {"caption": "Texto.", "cta": "CTA.", "hashtags": ["construcao"]},
        "meta_access_token": "fake-token",
        "instagram_business_id": "ig-123",
        "facebook_page_id": "",
    }


def _fake_ig_result():
    return {"post_id": "ig-post-abc", "permalink": "https://www.instagram.com/p/abc/"}


def test_publish_post_transitions_to_published():
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    async def fake_get_with_client(request_id):
        return _fake_request_with_meta()

    async def fake_ig(ig_id, token, image_url, caption):
        return _fake_ig_result()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get_with_client),
        patch("app.agents.publisher.publish_to_instagram", side_effect=fake_ig),
        patch("app.tasks.pipeline.collect_metrics"),  # evita agendamento real
    ):
        result = publish_post.run(rid)

    assert result == rid
    assert ContentStatus.publishing in call_log
    assert ContentStatus.published in call_log


# ─── start_content_pipeline ─────────────────────────────────────


def test_start_pipeline_returns_task_id():
    """start_content_pipeline deve retornar um task_id (string)."""
    rid = _rid()
    mock_result = MagicMock()
    mock_result.id = "celery-task-abc123"

    with patch("app.tasks.pipeline.chain") as mock_chain:
        mock_chain.return_value.apply_async.return_value = mock_result
        task_id = start_content_pipeline(rid)

    assert task_id == "celery-task-abc123"


def test_start_pipeline_chains_correct_tasks():
    """start_content_pipeline deve encadear analyze→copy→design."""
    rid = _rid()
    mock_result = MagicMock()
    mock_result.id = "x"

    with patch("app.tasks.pipeline.chain") as mock_chain:
        mock_chain.return_value.apply_async.return_value = mock_result
        start_content_pipeline(rid)

        # Verifica que chain foi chamado com 3 tasks
        args = mock_chain.call_args[0]
        assert len(args) == 3


# ─── Testes Multi-Foto (Story 6.2) ───────────────────────────────


def _fake_request_with_client_multi(content_type="carousel"):
    r = _fake_request_with_client()
    r["photo_keys"] = ["uploads/a.jpg", "uploads/b.jpg"]
    r["photo_urls"] = ["https://r2.example.com/a.jpg", "https://r2.example.com/b.jpg"]
    r["content_type"] = content_type
    return r


# ── analyze_photo multi-foto ──

def test_analyze_photo_multi_photo_analyses_all():
    """Multi-foto: analyze_photo_with_ai chamado para cada foto; analysis_result tem 'photos'."""
    rid = _rid()
    update_log = []
    analyze_calls = []

    async def fake_update(request_id, status, **kwargs):
        update_log.append((status, kwargs))

    async def fake_get(request_id):
        return _fake_request_with_client_multi("carousel")

    async def fake_ai(photo_url, brand_profile, photo_key="", user_context=None):
        analyze_calls.append(photo_url)
        return _fake_ai_analysis()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.analyst.analyze_photo_with_ai", side_effect=fake_ai),
    ):
        result = analyze_photo.run(rid)

    assert result == rid
    assert len(analyze_calls) == 2

    result_data = next(
        (kw.get("result_data") for _, kw in update_log if "result_data" in kw),
        None,
    )
    assert result_data is not None
    assert "photos" in result_data
    assert len(result_data["photos"]) == 2


def test_analyze_photo_multi_photo_bad_first_fails():
    """Multi-foto: se primeira foto for bad → status=failed."""
    rid = _rid()
    update_log = []

    async def fake_update(request_id, status, **kwargs):
        update_log.append(status)

    async def fake_get(request_id):
        return _fake_request_with_client_multi("carousel")

    async def fake_ai(photo_url, brand_profile, photo_key="", user_context=None):
        return {**_fake_ai_analysis(), "quality": "bad", "quality_reason": "dark"}

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.analyst.analyze_photo_with_ai", side_effect=fake_ai),
    ):
        analyze_photo.run(rid)

    assert ContentStatus.failed in update_log


def test_analyze_photo_multi_photo_bad_second_fails():
    """Multi-foto: se segunda foto for bad → status=failed."""
    rid = _rid()
    update_log = []
    call_count = [0]

    async def fake_update(request_id, status, **kwargs):
        update_log.append(status)

    async def fake_get(request_id):
        return _fake_request_with_client_multi("carousel")

    async def fake_ai(photo_url, brand_profile, photo_key="", user_context=None):
        call_count[0] += 1
        if call_count[0] == 2:
            return {**_fake_ai_analysis(), "quality": "bad", "quality_reason": "blurry"}
        return _fake_ai_analysis()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.analyst.analyze_photo_with_ai", side_effect=fake_ai),
    ):
        analyze_photo.run(rid)

    assert ContentStatus.failed in update_log


def test_analyze_photo_single_photo_retrocompat():
    """Foto única sem photo_keys → comportamento original."""
    rid = _rid()
    call_log = []
    analyze_calls = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    async def fake_get(request_id):
        return _fake_request_with_client()  # sem photo_keys

    async def fake_ai(photo_url, brand_profile, photo_key="", user_context=None):
        analyze_calls.append(photo_url)
        return _fake_ai_analysis()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.analyst.analyze_photo_with_ai", side_effect=fake_ai),
    ):
        analyze_photo.run(rid)

    assert len(analyze_calls) == 1
    assert ContentStatus.copy in call_log


# ── generate_copy multi-foto ──

def test_generate_copy_with_multi_photo_analysis():
    """generate_copy funciona com analysis_result contendo 'photos'."""
    rid = _rid()
    copy_inputs = []

    async def fake_update(request_id, status, **kwargs):
        pass

    async def fake_get(request_id):
        r = _fake_request_with_client_multi("carousel")
        r["analysis_result"] = {
            **_fake_ai_analysis(),
            "photos": [_fake_ai_analysis(), _fake_ai_analysis()],
        }
        return r

    async def fake_ai(analysis_result, brand_profile, **kwargs):
        copy_inputs.append(analysis_result)
        return _fake_ai_copy()

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.tasks.pipeline._save_caption_variants", new_callable=AsyncMock),
        patch("app.agents.copywriter.generate_copy_with_ai", side_effect=fake_ai),
    ):
        result = generate_copy.run(rid)

    assert result == rid
    assert "photos" in copy_inputs[0]


# ── prepare_design multi-foto ──

def test_prepare_design_before_after_calls_compositor():
    """content_type=before_after → process_before_after_two_photos chamado."""
    rid = _rid()
    compositor_calls = []

    async def fake_update(request_id, status, **kwargs):
        pass

    async def fake_get(request_id):
        return _fake_request_with_client_multi("before_after")

    async def fake_compositor(request_id, before_url, before_key, after_url, after_key, analysis, brand):
        compositor_calls.append((before_url, after_url))
        return {**_fake_ai_design(), "type": "before_after"}

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.designer.process_before_after_two_photos", side_effect=fake_compositor),
    ):
        result = prepare_design.run(rid)

    assert result == rid
    assert len(compositor_calls) == 1
    assert compositor_calls[0][0] == "https://r2.example.com/a.jpg"
    assert compositor_calls[0][1] == "https://r2.example.com/b.jpg"


def test_prepare_design_carousel_processes_each_photo():
    """content_type=carousel → process_image chamado N vezes; design_result tem design_keys."""
    rid = _rid()
    process_calls = []
    saved_designs = []

    async def fake_update(request_id, status, **kwargs):
        if "result_data" in kwargs:
            saved_designs.append(kwargs["result_data"])

    async def fake_get(request_id):
        return _fake_request_with_client_multi("carousel")

    async def fake_ai(request_id, photo_url, analysis_result, brand_profile, photo_key=""):
        process_calls.append(request_id)
        return {**_fake_ai_design(), "r2_key": f"processed/{request_id}/final.jpg"}

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.designer.process_image", side_effect=fake_ai),
    ):
        result = prepare_design.run(rid)

    assert result == rid
    assert len(process_calls) == 2
    assert saved_designs
    assert saved_designs[0]["type"] == "carousel"
    assert "design_keys" in saved_designs[0]
    assert len(saved_designs[0]["design_keys"]) == 2


# ── publish_post multi-foto ──

def _fake_request_with_meta_carousel():
    return {
        **_fake_request_with_client_multi("carousel"),
        "design_result": {
            "type": "carousel",
            "design_keys": ["processed/req/slide_0/final.jpg", "processed/req/slide_1/final.jpg"],
        },
        "copy_result": {"caption": "Texto.", "cta": "CTA.", "hashtags": ["construcao"]},
        "meta_access_token": "fake-token",
        "instagram_business_id": "ig-123",
        "facebook_page_id": "",
    }


def test_publish_post_carousel_transitions_to_published():
    """content_type=carousel → publish_carousel_to_instagram chamado; status=published."""
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    async def fake_get(request_id):
        return _fake_request_with_meta_carousel()

    async def fake_carousel(ig_id, token, image_urls, caption):
        return {"post_id": "carousel-post-123", "permalink": "https://www.instagram.com/p/xyz/"}

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.publisher.publish_carousel_to_instagram", side_effect=fake_carousel),
        patch("app.core.storage.generate_presigned_url", return_value="https://r2.example.com/signed.jpg"),
        patch("app.tasks.pipeline.collect_metrics"),
    ):
        result = publish_post.run(rid)

    assert result == rid
    assert ContentStatus.publishing in call_log
    assert ContentStatus.published in call_log


def test_publish_post_before_after_uses_single_photo_flow():
    """content_type=before_after → publish_to_instagram (não carousel)."""
    rid = _rid()
    ig_calls = []
    carousel_calls = []

    async def fake_update(request_id, status, **kwargs):
        pass

    async def fake_get(request_id):
        r = {
            **_fake_request_with_client_multi("before_after"),
            "design_result": {
                "type": "before_after",
                "r2_key": "processed/req/final.jpg",
            },
            "copy_result": {"caption": "T.", "cta": "C.", "hashtags": []},
            "meta_access_token": "tok",
            "instagram_business_id": "ig-456",
            "facebook_page_id": "",
        }
        return r

    async def fake_ig(ig_id, token, image_url, caption):
        ig_calls.append(image_url)
        return {"post_id": "ba-post-789", "permalink": "https://www.instagram.com/p/ba/"}

    async def fake_carousel(ig_id, token, image_urls, caption):
        carousel_calls.append(image_urls)
        return {"post_id": "c", "permalink": ""}

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.publisher.publish_to_instagram", side_effect=fake_ig),
        patch("app.agents.publisher.publish_carousel_to_instagram", side_effect=fake_carousel),
        patch("app.core.storage.generate_presigned_url", return_value="https://r2.example.com/ba.jpg"),
        patch("app.tasks.pipeline.collect_metrics"),
    ):
        publish_post.run(rid)

    assert len(ig_calls) == 1
    assert len(carousel_calls) == 0


def test_publish_post_carousel_token_expired_sets_failed():
    """carousel + token expirado → status=failed."""
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    async def fake_get(request_id):
        return _fake_request_with_meta_carousel()

    from app.agents.publisher import MetaAPIError

    async def fake_carousel(ig_id, token, image_urls, caption):
        raise MetaAPIError("Token expirado", code=190)

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request_with_client", side_effect=fake_get),
        patch("app.agents.publisher.publish_carousel_to_instagram", side_effect=fake_carousel),
        patch("app.core.storage.generate_presigned_url", return_value="https://r2.example.com/signed.jpg"),
    ):
        publish_post.run(rid)

    assert ContentStatus.failed in call_log
