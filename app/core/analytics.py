"""
Analytics — wrapper Posthog. No-op se POSTHOG_API_KEY não configurado.
"""
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    key = os.getenv("POSTHOG_API_KEY")
    if not key:
        return None
    try:
        import posthog as ph
        ph.api_key = key
        ph.host = os.getenv("POSTHOG_HOST", "https://app.posthog.com")
        ph.disabled = False
        _client = ph
    except Exception:
        logger.warning("posthog não disponível — analytics desabilitado")
        _client = False
    return _client if _client else None


def track(distinct_id: str, event: str, properties: dict[str, Any] | None = None) -> None:
    client = _get_client()
    if not client:
        return
    try:
        client.capture(distinct_id, event, properties or {})
    except Exception:
        pass  # analytics nunca bloqueia o fluxo principal
