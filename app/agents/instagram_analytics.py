"""
Instagram Analytics — métricas de conta via Meta Graph API v21.0.

Segue o mesmo contrato de publisher.py: recebe access_token por parâmetro
para suportar múltiplos clientes (multi-tenant).
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com/v21.0"
TIMEOUT = 30.0


async def _meta_get(endpoint: str, params: dict) -> dict:
    """GET na Graph API com tratamento de erro #190 (token expirado/inválido)."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(f"{GRAPH_BASE}/{endpoint}", params=params)
            body = resp.json()
        except httpx.RequestError as exc:
            return {"error": str(exc), "code": 500}

    if "error" in body:
        code = body["error"].get("code")
        if code == 190:
            return {
                "error": "Token Meta expirou ou foi revogado. Reautentique a conta.",
                "code": 190,
            }
        return {"error": body["error"].get("message", "Erro desconhecido na Graph API"), "code": code}

    return {"data": body.get("data", []), "status": 200}


async def get_instagram_analytics_30d(
    ig_business_id: str,
    access_token: str,
) -> dict:
    """
    Retorna métricas de conta dos últimos 30 dias para um Instagram Business.

    Args:
        ig_business_id: Instagram Business Account ID do cliente.
        access_token: Long-Lived Token Meta do cliente (por parâmetro — multi-tenant).

    Returns:
        dict com reach_total, reach_daily, follower_growth, follower_daily,
        accounts_engaged, profile_views, collected_at.
        Em caso de erro: {"error": str, "code": int}.
    """
    if not access_token:
        return {"error": "Token Meta não configurado para esta conta.", "code": 401}

    now = datetime.now(timezone.utc)
    since = int((now - timedelta(days=30)).timestamp())
    until = int(now.timestamp())

    # Chamada 1 — série temporal diária: alcance + contagem de seguidores
    series_res = await _meta_get(
        f"{ig_business_id}/insights",
        {
            "metric": "reach,follower_count",
            "period": "day",
            "since": since,
            "until": until,
            "access_token": access_token,
        },
    )
    if "error" in series_res:
        return series_res

    # Chamada 2 — engajamento consolidado (período days_28)
    eng_res = await _meta_get(
        f"{ig_business_id}/insights",
        {
            "metric": "accounts_engaged,profile_views",
            "period": "days_28",
            "access_token": access_token,
        },
    )
    if "error" in eng_res:
        return eng_res

    # Parse — séries temporais
    reach_daily: list[dict] = []
    follower_daily: list[dict] = []

    for metric in series_res["data"]:
        values = metric.get("values", [])
        parsed = [{"date": v["end_time"][:10], "value": v["value"]} for v in values]
        if metric["name"] == "reach":
            reach_daily = parsed
        elif metric["name"] == "follower_count":
            follower_daily = parsed

    reach_total = sum(d["value"] for d in reach_daily)

    # Crescimento líquido = último valor absoluto − primeiro valor absoluto.
    # follower_count retorna contagem cumulativa por dia, não delta.
    follower_growth = (
        follower_daily[-1]["value"] - follower_daily[0]["value"]
        if len(follower_daily) >= 2
        else 0
    )

    # Parse — engajamento (days_28 retorna um único ponto por métrica)
    accounts_engaged = 0
    profile_views = 0
    for metric in eng_res["data"]:
        val = metric["values"][-1]["value"] if metric.get("values") else 0
        if metric["name"] == "accounts_engaged":
            accounts_engaged = val
        elif metric["name"] == "profile_views":
            profile_views = val

    logger.info(
        f"[instagram_analytics] ig={ig_business_id} "
        f"reach={reach_total} followers_delta={follower_growth} engaged={accounts_engaged}"
    )

    return {
        "period_days": 30,
        "reach_total": reach_total,
        "reach_daily": reach_daily,
        "follower_growth": follower_growth,
        "follower_daily": follower_daily,
        "accounts_engaged": accounts_engaged,
        "profile_views": profile_views,
        "collected_at": now.isoformat(),
    }
