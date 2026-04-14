"""
Endpoints de Onboarding.
Fluxo conversacional com Claude para coletar brand_profile do cliente.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.auth import get_current_client
from app.core.database import get_db
from app.models.client import Client
from app.agents import onboarding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    message: str


class OnboardingReply(BaseModel):
    reply: str
    done: bool


class OnboardingStatus(BaseModel):
    status: str  # "not_started" | "in_progress" | "done"
    brand_profile: dict | None = None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/start", response_model=OnboardingReply, status_code=200)
async def start_onboarding(
    current_client: Client = Depends(get_current_client),
):
    """Inicia (ou reinicia) o onboarding do cliente autenticado."""
    result = await onboarding.start_session(str(current_client.id))
    return OnboardingReply(reply=result["last_message"], done=False)


@router.post("/message", response_model=OnboardingReply)
async def send_message(
    body: MessageRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Envia uma mensagem para o onboarding e recebe a resposta do Claude."""
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="Mensagem não pode ser vazia")

    result = await onboarding.process_message(str(current_client.id), body.message)

    # Salva brand_profile no banco quando onboarding é concluído
    if result["done"] and result.get("brand_profile"):
        db_result = await db.execute(
            select(Client).where(Client.id == current_client.id)
        )
        client = db_result.scalar_one_or_none()
        if client:
            client.brand_profile = result["brand_profile"]
            await db.commit()
            logger.info(f"[onboarding] brand_profile salvo client_id={current_client.id}")

    return OnboardingReply(reply=result["reply"], done=result["done"])


@router.get("/status", response_model=OnboardingStatus)
async def get_status(
    current_client: Client = Depends(get_current_client),
):
    """Retorna o status atual do onboarding do cliente."""
    session = await onboarding.get_session(str(current_client.id))
    if session is None:
        return OnboardingStatus(status="not_started")
    if session.get("done"):
        return OnboardingStatus(status="done", brand_profile=session.get("brand_profile"))
    return OnboardingStatus(status="in_progress")
