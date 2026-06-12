"""
Helpers para OAuth Instagram (API direta — sem Facebook Login).
"""

from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException
from jose import JWTError, jwt

INSTAGRAM_AUTH_URL = "https://api.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_GRAPH_BASE = "https://graph.instagram.com"

OAUTH_SCOPES = "instagram_business_basic,instagram_business_content_publish"


# ─── State JWT (CSRF) ────────────────────────────────────────────

def create_state_token(client_id: str, secret: str) -> str:
    """Gera JWT de curta duração (5 min) para uso como state no OAuth."""
    payload = {
        "client_id": client_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_state_token(state: str, secret: str) -> str:
    """Decodifica o state JWT e retorna client_id. Levanta 400 se inválido."""
    try:
        payload = jwt.decode(state, secret, algorithms=["HS256"])
        return payload["client_id"]
    except (JWTError, KeyError):
        raise HTTPException(status_code=400, detail="State inválido ou expirado.")


# ─── URL de autorização ──────────────────────────────────────────

def build_auth_url(app_id: str, redirect_uri: str, state: str) -> str:
    """Monta a URL de autorização da Instagram API."""
    return (
        f"{INSTAGRAM_AUTH_URL}"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={OAUTH_SCOPES}"
        f"&response_type=code"
        f"&state={state}"
    )


# ─── Troca de tokens ─────────────────────────────────────────────

async def exchange_code_for_short_token(
    code: str,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
) -> str:
    """
    Troca o authorization code por Short-Lived Token (~1 hora).
    POST https://api.instagram.com/oauth/access_token
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            INSTAGRAM_TOKEN_URL,
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao trocar o code por token: {resp.text}",
        )
    return resp.json()["access_token"]


async def exchange_for_long_lived_token(
    short_token: str,
    app_id: str,  # não usado pela Instagram API, mantido por compatibilidade de assinatura
    app_secret: str,
) -> tuple[str, datetime]:
    """
    Troca o Short-Lived Token por Long-Lived Token (~60 dias).
    GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token
    Retorna (long_lived_token, expires_at).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{INSTAGRAM_GRAPH_BASE}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret,
                "access_token": short_token,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao obter Long-Lived Token: {resp.text}",
        )
    data = resp.json()
    long_token = data["access_token"]
    expires_in_seconds = data.get("expires_in", 5_184_000)  # padrão 60 dias
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    return long_token, expires_at


async def refresh_long_lived_token(long_token: str) -> tuple[str, datetime]:
    """
    Renova um Long-Lived Token Instagram válido (não requer app_secret).
    GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token
    Retorna (new_token, new_expires_at).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{INSTAGRAM_GRAPH_BASE}/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": long_token,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao renovar token Instagram: {resp.text}",
        )
    data = resp.json()
    new_token = data["access_token"]
    expires_in_seconds = data.get("expires_in", 5_184_000)
    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    return new_token, new_expires_at


# ─── Busca de informações do usuário Instagram ──────────────────

async def get_instagram_user_info(long_token: str) -> tuple[str, str]:
    """
    Busca user_id e username via Instagram API.
    GET https://graph.instagram.com/me?fields=user_id,username
    Retorna (ig_user_id, ig_username).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{INSTAGRAM_GRAPH_BASE}/me",
            params={
                "fields": "user_id,username",
                "access_token": long_token,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao buscar informações da conta Instagram: {resp.text}",
        )
    data = resp.json()
    ig_user_id = str(data.get("user_id") or data.get("id", ""))
    ig_username = data.get("username", "")
    if not ig_user_id:
        raise HTTPException(
            status_code=400,
            detail="Não foi possível obter o ID da conta Instagram.",
        )
    return ig_user_id, ig_username
