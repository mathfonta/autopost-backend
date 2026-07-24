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


class SetupRequest(BaseModel):
    company_name: str
    segment: str
    tone: str
    colors: str = ""


class ScoutStatusResponse(BaseModel):
    scout_status: str  # pending | running | done | skipped | failed
    scout_insights: dict | None = None


class ScoutAcceptResponse(BaseModel):
    updated: bool
    segment: str | None = None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/setup", status_code=204)
async def setup_onboarding(
    body: SetupRequest,
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """Salva brand_profile diretamente a partir do formulário do wizard — sem agente Claude."""
    brand_profile = {
        "company_name": body.company_name.strip(),
        "segment": body.segment,
        "tone": body.tone,
        "colors": body.colors.strip(),
    }
    db_result = await db.execute(
        select(Client).where(Client.id == current_client.id)
    )
    client = db_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    client.brand_profile = brand_profile
    await db.commit()
    logger.info(f"[onboarding] setup direto salvo client_id={current_client.id}")
    return None


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
    # Se brand_profile já foi salvo (via /setup ou agente), onboarding está concluído
    if current_client.brand_profile:
        return OnboardingStatus(status="done", brand_profile=current_client.brand_profile)

    session = await onboarding.get_session(str(current_client.id))
    if session is None:
        return OnboardingStatus(status="not_started")
    if session.get("done"):
        return OnboardingStatus(status="done", brand_profile=session.get("brand_profile"))
    return OnboardingStatus(status="in_progress")


# ─── Agente Scout (Epic 22, Story 22.5) ───────────────────────────────────────

@router.get("/scout", response_model=ScoutStatusResponse)
async def get_scout_status(
    current_client: Client = Depends(get_current_client),
):
    """
    Retorna o status da análise do Agente Scout e, quando concluída (`done`),
    um resumo do `scout_insights` (incluindo `suggested_segment`, se houver).
    Quando não `done`, `scout_insights` vem sempre `None` — mesmo que exista
    um relatório de uma execução anterior, para não confundir o frontend
    sobre qual execução o status se refere.
    """
    scout_status = current_client.scout_status or "pending"
    scout_insights = None
    if scout_status == "done":
        brand_profile = current_client.brand_profile or {}
        scout_insights = brand_profile.get("scout_insights")

    return ScoutStatusResponse(scout_status=scout_status, scout_insights=scout_insights)


@router.post("/scout/accept", response_model=ScoutAcceptResponse)
async def accept_scout_suggestion(
    current_client: Client = Depends(get_current_client),
    db: AsyncSession = Depends(get_db),
):
    """
    Aplica a sugestão de segmento do Scout ao `segment` declarado do cliente —
    única via pela qual o Scout altera um campo declarado, e só por ação
    explícita do usuário (Decisão #2 do Epic 22). Lê o `suggested_segment`
    diretamente do banco (não aceita valor enviado pelo cliente) para nunca
    permitir gravar um segmento fora do que o próprio Scout já validou contra
    a lista fixa (ver app/agents/scout.py:FIXED_SEGMENTS).
    """
    db_result = await db.execute(
        select(Client).where(Client.id == current_client.id)
    )
    client = db_result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    brand_profile = client.brand_profile or {}
    scout_insights = brand_profile.get("scout_insights") or {}
    suggested_segment = scout_insights.get("suggested_segment") if client.scout_status == "done" else None

    if not suggested_segment:
        raise HTTPException(status_code=400, detail="Nenhuma sugestão de segmento disponível para aceitar.")

    updated_profile = dict(brand_profile)
    updated_profile["segment"] = suggested_segment
    client.brand_profile = updated_profile
    await db.commit()

    logger.info(
        f"[onboarding/scout] client_id={client.id} aceitou sugestão de segmento: {suggested_segment!r}"
    )
    return ScoutAcceptResponse(updated=True, segment=suggested_segment)
