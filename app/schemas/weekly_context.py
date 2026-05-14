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
    created_at: datetime

    model_config = {"from_attributes": True}


class StreakResponse(BaseModel):
    streak: int
    week_days: list[bool]
    week_goal: int = 5
