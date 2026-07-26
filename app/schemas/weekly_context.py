"""
Schemas Pydantic para WeeklyContext (Story 13.4).
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class WeeklyContextResponse(BaseModel):
    id: UUID
    week_of: date
    segment: str
    summary: str | None
    hashtags: list[str] | None
    suggested_time: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BestPostingTimeResponse(BaseModel):
    """Resposta do GET /insights/best-posting-time (Epic 19, Story 19.3).

    `fonte="sem_dados"` indica que não há histórico nem pesquisa Exa
    suficientes para uma recomendação real — `horario` vem `None` e
    `mensagem` explica o motivo, em vez de apresentar um horário estático
    como se fosse uma análise de dados.
    """
    horario: str | None
    fonte: Literal["historico", "exa", "sem_dados"]
    confianca: Literal["alta", "media", "baixa"]
    mensagem: str | None = None


class StreakResponse(BaseModel):
    streak: int
    week_days: list[bool]
    week_goal: int = 5
