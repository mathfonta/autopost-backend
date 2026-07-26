"""
Schemas Pydantic para WeeklyContext (Story 13.4).
"""

from datetime import date, datetime
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
    """Resposta do GET /insights/best-posting-time (Epic 19, Story 19.3)."""
    horario: str
    fonte: str
    confianca: str


class StreakResponse(BaseModel):
    streak: int
    week_days: list[bool]
    week_goal: int = 5
