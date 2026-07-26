"""
Testes da task de publicação agendada (Story 19.2 — Epic 19).
Não conecta ao banco real — usa mocks de WorkerSessionLocal.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.tasks.pipeline import publish_scheduled_posts


def _mock_session_ctx(mock_db):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_db_with_claimed(ids: list[uuid.UUID]):
    mock_db = AsyncMock()
    fake_result = MagicMock()
    fake_result.fetchall.return_value = [(rid,) for rid in ids]
    mock_db.execute = AsyncMock(return_value=fake_result)
    mock_db.commit = AsyncMock()
    return mock_db


def test_publish_scheduled_posts_dispatches_due_posts():
    """AC1/AC2 — posts reivindicados (scheduled_for já passou) disparam publish_post.delay."""
    ids = [uuid.uuid4(), uuid.uuid4()]
    mock_db = _mock_db_with_claimed(ids)

    with (
        patch("app.core.database.WorkerSessionLocal", return_value=_mock_session_ctx(mock_db)),
        patch("app.tasks.pipeline.publish_post") as mock_publish,
    ):
        mock_publish.delay = MagicMock()
        result = publish_scheduled_posts.run()

    assert result == "claimed=2"
    assert mock_publish.delay.call_count == 2
    dispatched = {call.args[0] for call in mock_publish.delay.call_args_list}
    assert dispatched == {str(i) for i in ids}


def test_publish_scheduled_posts_no_due_posts_dispatches_nothing():
    """AC2 (idempotência) — quando o claim não reivindica nenhuma linha (ex.: outro
    tick do Beat já pegou tudo), NENHUM publish_post é disparado novamente."""
    mock_db = _mock_db_with_claimed([])

    with (
        patch("app.core.database.WorkerSessionLocal", return_value=_mock_session_ctx(mock_db)),
        patch("app.tasks.pipeline.publish_post") as mock_publish,
    ):
        mock_publish.delay = MagicMock()
        result = publish_scheduled_posts.run()

    assert result == "claimed=0"
    mock_publish.delay.assert_not_called()


def test_publish_scheduled_posts_query_filters_status_and_time():
    """AC2/AC3 — o UPDATE reivindica só status=scheduled com scheduled_for <= now."""
    mock_db = _mock_db_with_claimed([])

    with patch("app.core.database.WorkerSessionLocal", return_value=_mock_session_ctx(mock_db)):
        publish_scheduled_posts.run()

    stmt = mock_db.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "content_requests" in compiled
    assert "scheduled_for" in compiled
    assert "UPDATE" in compiled.upper()
    assert "RETURNING" in compiled.upper()


def test_publish_scheduled_posts_captures_failure_without_raising():
    """Falha ao reivindicar (ex.: banco indisponível) é capturada e logada, nunca propagada."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("connection refused"))

    with (
        patch("app.core.database.WorkerSessionLocal", return_value=_mock_session_ctx(mock_db)),
        patch("app.tasks.pipeline.publish_post") as mock_publish,
    ):
        mock_publish.delay = MagicMock()
        result = publish_scheduled_posts.run()  # não deve levantar exceção

    assert result.startswith("error:")
    mock_publish.delay.assert_not_called()
