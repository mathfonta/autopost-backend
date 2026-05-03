"""
Endpoints de autenticação.
Usa Supabase Auth como provider — senhas nunca tocam nosso backend.
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.core.database import get_db
from app.core.auth import get_current_client
from app.core.supabase import supabase_sign_up, supabase_sign_in, supabase_refresh, supabase_update_password, supabase_reset_password_email
from app.models.client import Client
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    ForgotPasswordRequest,
    UpdatePasswordRequest,
    UpdateProfileRequest,
    TokenResponse,
    ClientResponse,
)
from app.core.limiter import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


# ─── Register ────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/hour")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Cria conta no Supabase Auth + registro Client no banco."""

    # 1. Verifica se email já existe no nosso banco
    result = await db.execute(select(Client).where(Client.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email já cadastrado")

    # 2. Cria usuário no Supabase Auth
    try:
        auth_response = await supabase_sign_up(body.email, body.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao criar conta: {str(e)}")

    if not auth_response.user:
        raise HTTPException(status_code=400, detail="Erro ao criar usuário no Auth")

    # 3. Cria Client no banco com o UUID do Supabase
    client = Client(
        id=uuid.UUID(str(auth_response.user.id)),
        email=body.email,
        name=body.name,
    )
    db.add(client)
    await db.commit()

    # 4. Retorna tokens — se session for None (email confirmation ativo), faz login
    session = auth_response.session
    if not session:
        try:
            login_response = await supabase_sign_in(body.email, body.password)
            session = login_response.session
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Conta criada mas erro ao autenticar: {str(e)}")
    if not session:
        raise HTTPException(status_code=400, detail="Conta criada. Confirme o email para fazer login.")
    return TokenResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in or 3600,
    )


# ─── Login ───────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Autentica usuário e retorna tokens JWT."""
    try:
        auth_response = await supabase_sign_in(body.email, body.password)
    except Exception:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")

    if not auth_response.session:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")

    session = auth_response.session
    return TokenResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in or 3600,
    )


# ─── Refresh ─────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    """Renova access_token usando refresh_token."""
    try:
        auth_response = await supabase_refresh(body.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token inválido ou expirado")

    session = auth_response.session
    return TokenResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in or 3600,
    )


# ─── Forgot Password ─────────────────────────────────────────

@router.post("/forgot-password", status_code=204)
@limiter.limit("5/hour")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    """Envia e-mail de recuperação. Sempre retorna 204 (não revela se email existe)."""
    settings = get_settings()
    redirect_to = f"{settings.FRONTEND_URL}/reset-password"
    try:
        await supabase_reset_password_email(body.email, redirect_to)
    except Exception:
        pass  # silencioso — não revela se o email existe
    return None


# ─── Update Password (recovery flow) ────────────────────────

@router.post("/update-password", status_code=204)
async def update_password(body: UpdatePasswordRequest):
    """Atualiza senha usando o access_token recebido do link de recuperação Supabase."""
    try:
        await supabase_update_password(body.access_token, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=400, detail="Não foi possível atualizar a senha")
    return None


# ─── Me ──────────────────────────────────────────────────────

@router.get("/me", response_model=ClientResponse)
async def me(current_client: Client = Depends(get_current_client)):
    """Retorna dados do client autenticado."""
    return current_client


# ─── Update Profile ───────────────────────────────────────────

@router.patch("/profile", response_model=ClientResponse)
async def update_profile(
    body: UpdateProfileRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Atualiza configurações do perfil (ex: tom de voz)."""
    updated = False
    if body.voice_tone is not None:
        current_client.voice_tone = body.voice_tone
        updated = True

    if updated:
        await db.commit()
        await db.refresh(current_client)
    return current_client
