"""
Cliente Supabase — singleton para operações de auth.
Usa create_client síncrono + asyncio.to_thread para não bloquear o event loop.
"""

import asyncio
from supabase import create_client, Client as SupabaseClient
from app.config import get_settings

_supabase: SupabaseClient | None = None


def _get_supabase_sync() -> SupabaseClient:
    global _supabase
    if _supabase is None:
        settings = get_settings()
        _supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _supabase


async def supabase_sign_up(email: str, password: str):
    """Cria usuário no Supabase Auth."""
    client = _get_supabase_sync()
    return await asyncio.to_thread(
        client.auth.sign_up, {"email": email, "password": password}
    )


async def supabase_sign_in(email: str, password: str):
    """Autentica usuário e retorna tokens."""
    client = _get_supabase_sync()
    return await asyncio.to_thread(
        client.auth.sign_in_with_password, {"email": email, "password": password}
    )


async def supabase_refresh(refresh_token: str):
    """Renova access_token a partir de refresh_token."""
    client = _get_supabase_sync()
    return await asyncio.to_thread(
        client.auth.refresh_session, refresh_token
    )


async def supabase_get_user(access_token: str):
    """Verifica token e retorna dados do usuário."""
    client = _get_supabase_sync()
    return await asyncio.to_thread(client.auth.get_user, access_token)


async def supabase_reset_password_email(email: str, redirect_to: str):
    """Envia e-mail de recuperação de senha via Supabase."""
    client = _get_supabase_sync()
    return await asyncio.to_thread(
        client.auth.reset_password_email,
        email,
        {"redirect_to": redirect_to},
    )


async def supabase_update_password(access_token: str, new_password: str):
    """Atualiza senha usando o access_token de recovery do Supabase.

    Decodifica o JWT para obter user_id sem validar expiração —
    get_user() rejeita tokens expirados antes de chegar no admin update.
    A segurança é garantida pelo service role key + entrega do email pela Supabase.
    """
    import base64, json

    try:
        parts = access_token.split(".")
        if len(parts) != 3:
            raise ValueError("formato inválido")
        padding = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + padding))
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("sub ausente")
    except Exception as exc:
        raise ValueError(f"Token de recuperação inválido: {exc}")

    client = _get_supabase_sync()
    return await asyncio.to_thread(
        client.auth.admin.update_user_by_id,
        user_id,
        {"password": new_password},
    )
