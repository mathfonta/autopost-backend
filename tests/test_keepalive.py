"""
Testes da task de keep-alive do Supabase (Story 1.5 — Epic 1).
Não conecta ao banco real — usa mocks de WorkerSessionLocal.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.tasks.pipeline import keepalive_ping


def _mock_session_ctx(mock_db):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def test_keepalive_ping_success():
    """AC1, AC6a — executa SELECT 1 e retorna 'ok' quando o banco responde normalmente."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=None)

    with patch(
        "app.core.database.WorkerSessionLocal",
        return_value=_mock_session_ctx(mock_db),
    ):
        result = keepalive_ping.run()

    assert result == "ok"
    mock_db.execute.assert_called_once()


def test_keepalive_ping_captures_failure_without_raising():
    """AC3, AC6b — falha na query (ex.: banco pausado) é capturada e logada, nunca propagada."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("ENOTFOUND tenant/user postgres.x not found"))

    with patch(
        "app.core.database.WorkerSessionLocal",
        return_value=_mock_session_ctx(mock_db),
    ):
        result = keepalive_ping.run()  # não deve levantar exceção

    assert result.startswith("error:")
    assert "ENOTFOUND" in result
