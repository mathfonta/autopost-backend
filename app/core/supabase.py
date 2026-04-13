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
