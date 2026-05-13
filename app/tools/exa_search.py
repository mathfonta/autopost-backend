"""
Tool de Busca Web via Exa Search API — interface estável, provider plugável.

Uso:
    from app.tools.exa_search import search_exa_trends
    context = await search_exa_trends(segment="Construção civil", content_type="obra_realizada")
    # Retorna string formatada para injeção no prompt, ou None se desativado/falhar

Configuração (Railway → Variables):
    EXA_PROVIDER=exa        # ativa a busca — requer EXA_API_KEY
    EXA_PROVIDER=disabled   # padrão — zero overhead, nenhuma chamada externa
    EXA_API_KEY=...         # obter em exa.ai → API Keys

Cache:
    Resultados cacheados no Redis por 24h por (segment, content_type).
    Evita cobrar chamada Exa em cada post do mesmo usuário no mesmo dia.

Fallback:
    Qualquer falha (timeout, 4xx, 5xx, network) loga WARNING e retorna None.
    O pipeline continua normalmente sem contexto de mercado — nunca bloqueia.
"""

import logging
import os
from datetime import datetime, timedelta

import httpx

from app.core.redis import get_redis_client

logger = logging.getLogger(__name__)

EXA_BASE_URL = "https://api.exa.ai"
CACHE_TTL_SECONDS = 86400  # 24h

# Queries semânticas por content_type — mesmo estilo dos _VIRAL_TRIGGERS do copywriter
_CONTENT_TYPE_QUERIES: dict[str, str] = {
    "obra_realizada":      "acabamento construção civil residencial tendência qualidade",
    "obra_em_andamento":   "construção civil Brasil materiais inovação canteiro obra",
    "antes_depois":        "reforma residencial tendência design interiores transformação resultado",
    "engajamento":         "mercado imobiliário construção civil notícias destaque semana",
    "bastidores":          "gestão obra equipe construção profissional dia a dia",
    "reels":               "vídeo construção civil reforma tendência viral engajamento",
    "story":               "construção civil reforma dica rápida tendência",
    "carousel":            "passo a passo construção reforma materiais tutorial",
}


async def search_exa_trends(
    segment: str,
    content_type: str,
    days_back: int = 30,
) -> str | None:
    """
    Busca tendências recentes no Exa para o segmento e tipo de conteúdo informados.

    Args:
        segment:      Segmento do cliente (ex: "Construção civil", "Arquitetura")
        content_type: Tipo de conteúdo (ex: "obra_realizada", "antes_depois")
        days_back:    Janela de busca em dias (padrão: 30)

    Returns:
        String formatada com [CONTEXTO DE MERCADO RECENTE] pronta para injeção
        no prompt do copywriter, ou None se Exa estiver desativado ou falhar.
    """
    if os.getenv("EXA_PROVIDER", "disabled") != "exa":
        logger.debug("[exa] EXA_PROVIDER=disabled — retornando sem busca")
        return None

    if not os.getenv("EXA_API_KEY", ""):
        logger.warning("[exa] EXA_API_KEY não configurada — sem busca de tendências")
        return None

    # ── Cache Redis ──────────────────────────────────────────────────────────
    cache_key = f"exa:trends:{segment}:{content_type}"
    try:
        redis = get_redis_client()
        cached = await redis.get(cache_key)
        if cached:
            logger.info(f"[exa] cache hit — {cache_key}")
            return cached if cached != "null" else None
    except Exception as e:
        logger.warning(f"[exa] falha ao ler cache Redis: {e} — continuando sem cache")

    # ── Busca na API Exa ─────────────────────────────────────────────────────
    try:
        result = await _fetch_exa(segment, content_type, days_back)
    except Exception as e:
        logger.warning(f"[exa] falhou — continuando sem tendências: {e}")
        return None

    # ── Salvar no cache ──────────────────────────────────────────────────────
    try:
        redis = get_redis_client()
        await redis.setex(cache_key, CACHE_TTL_SECONDS, result if result else "null")
    except Exception as e:
        logger.warning(f"[exa] falha ao salvar cache Redis: {e}")

    return result


async def search_exa_raw(query: str, days_back: int = 7) -> list[str]:
    """
    Busca raw para uso no weekly intelligence (Story 13.4).
    Retorna lista de snippets sem cache.

    Args:
        query:     Query livre para o Exa
        days_back: Janela de busca em dias

    Returns:
        Lista de snippets de texto ou lista vazia se falhar
    """
    if os.getenv("EXA_PROVIDER", "disabled") != "exa" or not os.getenv("EXA_API_KEY", ""):
        return []

    try:
        start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime(
            "%Y-%m-%dT00:00:00Z"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{EXA_BASE_URL}/search",
                headers={
                    "x-api-key": os.getenv("EXA_API_KEY", ""),
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "numResults": 5,
                    "startPublishedDate": start_date,
                    "contents": {
                        "highlights": {
                            "numSentences": 3,
                            "highlightsPerUrl": 2,
                        },
                        "text": False,
                    },
                    "category": "news",
                },
            )
            response.raise_for_status()

        results = response.json().get("results", [])
        snippets = []
        for r in results[:3]:
            highlights = r.get("highlights", [])
            if highlights:
                snippets.append(" ".join(highlights[:2]))
        return snippets

    except Exception as e:
        logger.warning(f"[exa/raw] falhou para query '{query}': {e}")
        return []


# ─── Internals ───────────────────────────────────────────────────────────────

async def _fetch_exa(segment: str, content_type: str, days_back: int) -> str | None:
    """Executa a chamada HTTP ao Exa e formata o resultado."""
    start_date = (datetime.utcnow() - timedelta(days=days_back)).strftime(
        "%Y-%m-%dT00:00:00Z"
    )
    query = _build_query(segment, content_type)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{EXA_BASE_URL}/search",
            headers={
                "x-api-key": os.getenv("EXA_API_KEY", ""),
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "numResults": 5,
                "startPublishedDate": start_date,
                "contents": {
                    "highlights": {
                        "numSentences": 3,
                        "highlightsPerUrl": 2,
                    },
                    "text": False,  # só highlights — economiza tokens
                },
                "category": "news",
            },
        )
        response.raise_for_status()

    results = response.json().get("results", [])
    formatted = _format_for_prompt(results)

    if formatted:
        logger.info(
            f"[exa] tendências encontradas: {len(formatted)} chars "
            f"para segment={segment!r} content_type={content_type!r}"
        )
    else:
        logger.info(
            f"[exa] sem tendências para segment={segment!r} "
            f"content_type={content_type!r} — continuando normalmente"
        )

    return formatted


def _build_query(segment: str, content_type: str) -> str:
    """Monta query semântica baseada no segmento e tipo de conteúdo."""
    base = _CONTENT_TYPE_QUERIES.get(
        content_type,
        "construção civil tendências mercado",
    )
    return f"{base} {segment} site:br"


def _format_for_prompt(results: list) -> str | None:
    """Formata os highlights do Exa como bloco de contexto para o prompt."""
    snippets = []
    for r in results[:3]:
        highlights = r.get("highlights", [])
        if highlights:
            snippets.append(" ".join(highlights[:2]))

    if not snippets:
        return None

    lines = ["[CONTEXTO DE MERCADO RECENTE]"]
    for snippet in snippets:
        lines.append(f"• {snippet}")

    return "\n".join(lines)
