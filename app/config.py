"""
Configurações da aplicação via variáveis de ambiente.
Usa Pydantic Settings para validação automática.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ─── App ─────────────────────────────────────────────────
    APP_NAME: str = "AutoPost API"
    APP_VERSION: str = "1.0.0"
    ENV: str = "development"  # development | production

    # ─── Banco de Dados ──────────────────────────────────────
    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str

    # ─── Redis / Celery ──────────────────────────────────────
    REDIS_URL: str

    # ─── Auth ────────────────────────────────────────────────
    JWT_SECRET: str
    JWT_EXPIRE_MINUTES: int = 60

    # ─── Cloudflare R2 ───────────────────────────────────────
    CLOUDFLARE_R2_BUCKET: str
    CLOUDFLARE_R2_ACCESS_KEY: str
    CLOUDFLARE_R2_SECRET_KEY: str
    CLOUDFLARE_R2_ENDPOINT: str

    # ─── IA ──────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str

    # ─── Meta ────────────────────────────────────────────────
    META_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""

    # ─── Add-ons opcionais ───────────────────────────────────
    GOOGLE_DRIVE_CLIENT_ID: str = ""
    GOOGLE_DRIVE_CLIENT_SECRET: str = ""
    DROPBOX_APP_KEY: str = ""
    DROPBOX_APP_SECRET: str = ""
    ONEDRIVE_CLIENT_ID: str = ""
    ONEDRIVE_CLIENT_SECRET: str = ""

    model_config = {"env_file": ".env", "case_sensitive": True}


@lru_cache
def get_settings() -> Settings:
    return Settings()
