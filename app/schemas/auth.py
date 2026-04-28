"""
Schemas Pydantic para autenticação.
"""

import uuid
from typing import Literal
from pydantic import BaseModel, EmailStr, field_validator


# ─── Requests ────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Senha deve ter no mínimo 6 caracteres")
        return v

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Nome não pode ser vazio")
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class UpdatePasswordRequest(BaseModel):
    access_token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Senha deve ter no mínimo 6 caracteres")
        return v


class UpdateProfileRequest(BaseModel):
    voice_tone: Literal["formal", "casual", "technical"] | None = None


# ─── Responses ───────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class ClientResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    plan: str
    brand_profile: dict
    voice_tone: str | None = "casual"
    is_active: bool

    model_config = {"from_attributes": True}
