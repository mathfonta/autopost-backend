"""
Testes unitários para app/tools/exa_search.py

Cenários cobertos:
- Provider desativado (EXA_PROVIDER=disabled) → retorna None sem chamar API
- API key ausente → retorna None
- Sucesso com snippets → retorna bloco formatado
- Timeout da API → graceful fallback (None)
- Erro HTTP 4xx/5xx → graceful fallback (None)
- Cache hit → retorna sem chamar API
- Cache miss → chama API e salva no cache
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Fixtures ────────────────────────────────────────────────────────────────

EXA_RESPONSE_OK = {
    "results": [
        {
            "url": "https://exemplo.com.br/artigo-1",
            "highlights": [
                "Porcelanato grande formato domina o mercado de acabamentos em 2025.",
                "Vídeos antes e depois geram 4x mais saves que fotos estáticas.",
            ],
        },
        {
            "url": "https://exemplo.com.br/artigo-2",
            "highlights": [
                "Tom pessoal e próximo supera técnico em 67% dos posts virais de construção.",
            ],
        },
    ]
}

EXA_RESPONSE_EMPTY = {"results": []}

# ─── Env helpers ─────────────────────────────────────────────────────────────

ENV_EXA_ENABLED = {"EXA_PROVIDER": "exa", "EXA_API_KEY": "test-key"}
ENV_EXA_DISABLED = {"EXA_PROVIDER": "disabled", "EXA_API_KEY": "test-key"}
ENV_NO_KEY = {"EXA_PROVIDER": "exa", "EXA_API_KEY": ""}


# ─── Testes: provider desativado ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_provider_returns_none():
    """Quando EXA_PROVIDER=disabled, retorna None sem tocar na API."""
    with patch.dict("os.environ", ENV_EXA_DISABLED, clear=False):
        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result is None


@pytest.mark.asyncio
async def test_missing_api_key_returns_none():
    """Quando EXA_API_KEY está vazia, retorna None."""
    with patch.dict("os.environ", ENV_NO_KEY, clear=False):
        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result is None


# ─── Testes: sucesso ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_success_returns_formatted_block():
    """Busca bem-sucedida retorna bloco [CONTEXTO DE MERCADO RECENTE] com bullets."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # cache miss
    mock_redis.setex = AsyncMock()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=EXA_RESPONSE_OK)

    with (
        patch.dict("os.environ", ENV_EXA_ENABLED, clear=False),
        patch("app.tools.exa_search.get_redis_client", return_value=mock_redis),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result is not None
    assert "[CONTEXTO DE MERCADO RECENTE]" in result
    assert "•" in result
    assert "Porcelanato" in result or "saves" in result


@pytest.mark.asyncio
async def test_empty_results_returns_none():
    """Quando o Exa não retorna resultados, retorna None."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=EXA_RESPONSE_EMPTY)

    with (
        patch.dict("os.environ", ENV_EXA_ENABLED, clear=False),
        patch("app.tools.exa_search.get_redis_client", return_value=mock_redis),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result is None


# ─── Testes: fallback ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_returns_none():
    """Timeout da API retorna None sem propagar exceção."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with (
        patch.dict("os.environ", ENV_EXA_ENABLED, clear=False),
        patch("app.tools.exa_search.get_redis_client", return_value=mock_redis),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("ConnectTimeout"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result is None


@pytest.mark.asyncio
async def test_http_error_returns_none():
    """Erro HTTP (4xx/5xx) retorna None sem propagar exceção."""
    import httpx

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock())
    )

    with (
        patch.dict("os.environ", ENV_EXA_ENABLED, clear=False),
        patch("app.tools.exa_search.get_redis_client", return_value=mock_redis),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result is None


# ─── Testes: cache ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_hit_returns_without_api_call():
    """Cache hit retorna o valor cacheado sem chamar a API."""
    cached_value = "[CONTEXTO DE MERCADO RECENTE]\n• Tendência cacheada do Redis"

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=cached_value)

    with (
        patch.dict("os.environ", ENV_EXA_ENABLED, clear=False),
        patch("app.tools.exa_search.get_redis_client", return_value=mock_redis),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result == cached_value
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_cache_null_returns_none():
    """Cache com valor 'null' (busca anterior sem resultados) retorna None."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="null")

    with (
        patch.dict("os.environ", ENV_EXA_ENABLED, clear=False),
        patch("app.tools.exa_search.get_redis_client", return_value=mock_redis),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result is None
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_success_saves_to_cache():
    """Busca bem-sucedida salva resultado no Redis com TTL correto."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=EXA_RESPONSE_OK)

    with (
        patch.dict("os.environ", ENV_EXA_ENABLED, clear=False),
        patch("app.tools.exa_search.get_redis_client", return_value=mock_redis),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.tools.exa_search import search_exa_trends
        result = await search_exa_trends("Construção civil", "obra_realizada")

    assert result is not None
    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    assert call_args[0][0] == "exa:trends:Construção civil:obra_realizada"
    assert call_args[0][1] == 86400  # 24h TTL
