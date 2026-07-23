"""
Testes da task Celery do Agente Scout — _run_scout_analysis_async (Story 22.3).

Testa a função async interna diretamente (mesmo padrão de
test_attack_sequence.py para _increment_attack_sequence), mockando
WorkerSessionLocal, fetch_recent_media e analyze_profile. Não testa o
wrapper síncrono da task (_run_sync/Celery) — só a lógica de negócio.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.pipeline import _run_scout_analysis_async

CLIENT_ID = "00000000-0000-0000-0000-000000000042"

MOCK_MEDIA = [{"id": "m1", "caption": "Cozinha planejada finalizada"}]

MOCK_REPORT = {
    "refined_niche": "móveis planejados sob medida",
    "recurring_topics": ["cozinhas planejadas"],
    "visual_style": "madeira clara, luz natural",
    "audience_notes": "casais montando o primeiro apê",
    "suggested_segment": None,
    "confidence": 0.6,
}


def _mock_client_obj(
    connected: bool = True,
    brand_profile: dict | None = None,
):
    client = MagicMock()
    client.id = CLIENT_ID
    client.instagram_business_id = "ig-999" if connected else None
    client.meta_access_token = "long-token-xyz" if connected else None
    client.brand_profile = brand_profile if brand_profile is not None else {
        "segment": "comércio", "tone": "profissional", "company_name": "Marcenaria Silva",
    }
    client.scout_status = "pending"
    client.scout_report = None
    return client


def _mock_session(client_obj):
    """Monta um WorkerSessionLocal() mockado que retorna client_obj no execute()."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=client_obj)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=db)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    return session_ctx, db


# ─── Caminho feliz ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scout_analysis_happy_path_merges_additively():
    """Caminho feliz: status vai a running->done, brand_profile ganha scout_insights
    SEM perder os campos declarados pelo usuário (AC3)."""
    client_obj = _mock_client_obj()
    session_ctx, db = _mock_session(client_obj)

    with (
        patch("app.core.database.WorkerSessionLocal", return_value=session_ctx),
        patch("app.tools.instagram_media.fetch_recent_media", new=AsyncMock(return_value=MOCK_MEDIA)),
        patch("app.agents.scout.analyze_profile", new=AsyncMock(return_value=MOCK_REPORT)),
    ):
        result = await _run_scout_analysis_async(CLIENT_ID)

    assert result == "done"
    assert client_obj.scout_status == "done"
    assert client_obj.scout_report == MOCK_REPORT
    # Campos declarados preservados (AC3)
    assert client_obj.brand_profile["segment"] == "comércio"
    assert client_obj.brand_profile["company_name"] == "Marcenaria Silva"
    # Enriquecimento aditivo
    assert client_obj.brand_profile["scout_insights"] == MOCK_REPORT
    assert db.commit.await_count >= 2  # ao menos: running + done


@pytest.mark.asyncio
async def test_scout_analysis_empty_media_skips_without_touching_brand_profile():
    """analyze_profile retornando None (mídia vazia) -> status skipped,
    brand_profile intocado (AC6)."""
    client_obj = _mock_client_obj()
    original_profile = dict(client_obj.brand_profile)
    session_ctx, db = _mock_session(client_obj)

    with (
        patch("app.core.database.WorkerSessionLocal", return_value=session_ctx),
        patch("app.tools.instagram_media.fetch_recent_media", new=AsyncMock(return_value=[])),
        patch("app.agents.scout.analyze_profile", new=AsyncMock(return_value=None)),
    ):
        result = await _run_scout_analysis_async(CLIENT_ID)

    assert result == "skipped_no_report"
    assert client_obj.scout_status == "skipped"
    assert client_obj.brand_profile == original_profile  # intocado
    assert client_obj.scout_report is None


@pytest.mark.asyncio
async def test_scout_analysis_no_connection_skips_without_calling_models():
    """Cliente sem instagram_business_id/token (desconectou entre enqueue e execução)
    -> skipped imediatamente, sem chamar fetch_recent_media nem analyze_profile."""
    client_obj = _mock_client_obj(connected=False)
    session_ctx, db = _mock_session(client_obj)

    with (
        patch("app.core.database.WorkerSessionLocal", return_value=session_ctx),
        patch("app.tools.instagram_media.fetch_recent_media", new=AsyncMock()) as mock_fetch,
        patch("app.agents.scout.analyze_profile", new=AsyncMock()) as mock_analyze,
    ):
        result = await _run_scout_analysis_async(CLIENT_ID)

    assert result == "skipped_no_connection"
    assert client_obj.scout_status == "skipped"
    mock_fetch.assert_not_called()
    mock_analyze.assert_not_called()


@pytest.mark.asyncio
async def test_scout_analysis_client_not_found_is_noop():
    """client_id inexistente -> retorna sem erro, sem tentar persistir nada."""
    session_ctx, db = _mock_session(None)

    with patch("app.core.database.WorkerSessionLocal", return_value=session_ctx):
        result = await _run_scout_analysis_async(CLIENT_ID)

    assert result == "client_not_found"
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_scout_analysis_model_failure_sets_failed_status():
    """Falha inesperada (ex.: exceção não tratada em analyze_profile) -> status failed,
    nunca propaga exceção para fora da task (AC6/AC7)."""
    client_obj = _mock_client_obj()
    session_ctx, db = _mock_session(client_obj)

    with (
        patch("app.core.database.WorkerSessionLocal", return_value=session_ctx),
        patch("app.tools.instagram_media.fetch_recent_media", new=AsyncMock(side_effect=Exception("erro inesperado"))),
    ):
        result = await _run_scout_analysis_async(CLIENT_ID)

    assert result == "failed"
    assert client_obj.scout_status == "failed"


@pytest.mark.asyncio
async def test_scout_analysis_status_transitions_pending_running_done():
    """AC7 — confirma a sequência de status: running é setado ANTES de chamar os modelos,
    done só depois que tudo terminou com sucesso."""
    client_obj = _mock_client_obj()
    session_ctx, db = _mock_session(client_obj)
    observed_statuses = []

    async def _fake_fetch(*args, **kwargs):
        observed_statuses.append(client_obj.scout_status)  # deve já estar "running" aqui
        return MOCK_MEDIA

    with (
        patch("app.core.database.WorkerSessionLocal", return_value=session_ctx),
        patch("app.tools.instagram_media.fetch_recent_media", new=_fake_fetch),
        patch("app.agents.scout.analyze_profile", new=AsyncMock(return_value=MOCK_REPORT)),
    ):
        await _run_scout_analysis_async(CLIENT_ID)

    assert observed_statuses == ["running"]
    assert client_obj.scout_status == "done"
