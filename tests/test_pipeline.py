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

    async def fake_ai(photo_url, brand_profile):
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

    async def fake_ai(photo_url, brand_profile):
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


def test_generate_copy_transitions_to_design():
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    with patch("app.tasks.pipeline._update_status", side_effect=fake_update):
        result = generate_copy.run(rid)

    assert result == rid
    assert ContentStatus.design in call_log


def test_generate_copy_sets_copy_result():
    rid = _rid()
    results = []

    async def fake_update(request_id, status, **kwargs):
        if "result_data" in kwargs:
            results.append(kwargs["result_data"])

    with patch("app.tasks.pipeline._update_status", side_effect=fake_update):
        generate_copy.run(rid)

    assert results
    copy = results[0]
    assert "caption" in copy
    assert "hashtags" in copy
    assert "cta" in copy


# ─── prepare_design ─────────────────────────────────────────────


def test_prepare_design_transitions_to_awaiting_approval():
    rid = _rid()
    call_log = []
    fake_req = _fake_request()
    fake_req.analysis_result = {"publish_clean": True}

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    async def fake_get(request_id):
        return fake_req

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request", side_effect=fake_get),
    ):
        result = prepare_design.run(rid)

    assert result == rid
    assert ContentStatus.awaiting_approval in call_log


def test_prepare_design_clean_photo_type():
    """publish_clean=True → design.type == clean_photo."""
    rid = _rid()
    results = []
    fake_req = _fake_request()
    fake_req.analysis_result = {"publish_clean": True}

    async def fake_update(request_id, status, **kwargs):
        if "result_data" in kwargs:
            results.append(kwargs["result_data"])

    async def fake_get(request_id):
        return fake_req

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request", side_effect=fake_get),
    ):
        prepare_design.run(rid)

    assert results
    assert results[0]["type"] == "clean_photo"


def test_prepare_design_card_type():
    """publish_clean=False → design.type == card."""
    rid = _rid()
    results = []
    fake_req = _fake_request()
    fake_req.analysis_result = {"publish_clean": False}

    async def fake_update(request_id, status, **kwargs):
        if "result_data" in kwargs:
            results.append(kwargs["result_data"])

    async def fake_get(request_id):
        return fake_req

    with (
        patch("app.tasks.pipeline._update_status", side_effect=fake_update),
        patch("app.tasks.pipeline._get_request", side_effect=fake_get),
    ):
        prepare_design.run(rid)

    assert results
    assert results[0]["type"] == "card"


# ─── publish_post ───────────────────────────────────────────────


def test_publish_post_transitions_to_published():
    rid = _rid()
    call_log = []

    async def fake_update(request_id, status, **kwargs):
        call_log.append(status)

    with patch("app.tasks.pipeline._update_status", side_effect=fake_update):
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
