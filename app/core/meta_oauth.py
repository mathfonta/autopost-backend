"""
Helpers para OAuth Meta (Facebook / Instagram).
Funções auxiliares para geração de state JWT, troca de tokens e busca de IDs.
"""

from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException
from jose import JWTError, jwt

GRAPH_BASE = "https://graph.facebook.com/v21.0"
OAUTH_DIALOG = "https://www.facebook.com/v21.0/dialog/oauth"
OAUTH_SCOPES = (
    "instagram_content_publish,"
    "pages_manage_posts,pages_read_engagement,"
    "pages_show_list"
)


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
    """Monta a URL de autorização do Meta OAuth com todos os scopes necessários."""
    return (
        f"{OAUTH_DIALOG}"
        f"?client_id={app_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={OAUTH_SCOPES}"
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
    Troca o authorization code por um Short-Lived Token (~1 hora).
    POST https://graph.facebook.com/v21.0/oauth/access_token
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{GRAPH_BASE}/oauth/access_token",
            data={
                "client_id": app_id,
                "client_secret": app_secret,
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
    app_id: str,
    app_secret: str,
) -> tuple[str, datetime]:
    """
    Troca o Short-Lived Token por Long-Lived Token (~60 dias).
    GET https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token
    Retorna (long_lived_token, expires_at).
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{GRAPH_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": short_token,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Erro ao obter Long-Lived Token: {resp.text}",
        )
    long_token = resp.json()["access_token"]
    expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    return long_token, expires_at


# ─── Busca de IDs IG / Facebook ──────────────────────────────────

async def get_instagram_business_info(
    long_token: str,
) -> tuple[str, str, str, str]:
    """
    Busca a primeira Página do Facebook que tenha uma conta Instagram Business.
    Retorna (facebook_page_id, facebook_page_name, ig_business_id, ig_username).
    Levanta 400 se nenhuma Página/conta IG Business for encontrada.
    """
    # 1. Listar páginas do usuário
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_BASE}/me/accounts",
            params={"access_token": long_token},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Erro ao buscar Páginas do Facebook.")

    pages = resp.json().get("data", [])
    if not pages:
        raise HTTPException(
            status_code=400,
            detail="Nenhuma Página do Facebook encontrada na sua conta.",
        )

    # 2. Para cada página, verificar se há IG Business Account
    for page in pages:
        page_id = page["id"]
        page_name = page.get("name", "")
        page_token = page.get("access_token", long_token)

        async with httpx.AsyncClient() as client:
            ig_resp = await client.get(
                f"{GRAPH_BASE}/{page_id}",
                params={
                    "fields": "instagram_business_account",
                    "access_token": page_token,
                },
            )
        if ig_resp.status_code != 200:
            continue

        ig_account = ig_resp.json().get("instagram_business_account")
        if not ig_account:
            continue

        ig_id = ig_account["id"]

        # 3. Buscar username do Instagram
        async with httpx.AsyncClient() as client:
            user_resp = await client.get(
                f"{GRAPH_BASE}/{ig_id}",
                params={
                    "fields": "username",
                    "access_token": page_token,
                },
            )
        ig_username = ""
        if user_resp.status_code == 200:
            ig_username = user_resp.json().get("username", "")

        return page_id, page_name, ig_id, ig_username

    raise HTTPException(
        status_code=400,
        detail=(
            "Nenhuma conta Instagram Business encontrada nas suas Páginas. "
            "Certifique-se de que sua conta Instagram está configurada como Business "
            "e vinculada a uma Página do Facebook."
        ),
    )
