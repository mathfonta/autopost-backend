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
    CLOUDFLARE_R2_PUBLIC_URL: str = ""  # URL pública das imagens processadas

    # ─── IA ──────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str
    GEMINI_API_KEY: str = ""           # Transcrição de áudio via Gemini (provider padrão)
    OPENAI_API_KEY: str = ""           # Transcrição de áudio via Whisper (provider alternativo)
    TRANSCRIPTION_PROVIDER: str = "gemini"  # "gemini" | "whisper"
    COPY_PROVIDER: str = "claude"      # "claude" | "gemini"
    EXA_PROVIDER: str = "disabled"    # "exa" | "disabled"
    EXA_API_KEY: str = ""             # Exa Search API key — exa.ai

    # ─── Meta ────────────────────────────────────────────────
    META_ACCESS_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""

    # ─── Meta OAuth ──────────────────────────────────────────
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_REDIRECT_URI: str = ""  # ex: https://espectra-api-production.up.railway.app/meta/callback
    FRONTEND_URL: str = "http://localhost:3000"  # ex: https://autopost-frontend-one.vercel.app

    # ─── Segundo Cérebro ─────────────────────────────────────
    # Em produção/local: aponta para o vault Obsidian
    # Ex: C:\Users\Matheus\OneDrive\Obsidian\AutoPost\🧠 Cerebro
    # Fallback automático no reader.py: .cerebro-autopost/ na raiz do projeto
    CEREBRO_PATH: str = ""

    # Cérebro Global — cross-projeto
    # Ex: C:\Users\Matheus\OneDrive\Obsidian\🌐 Global
    GLOBAL_CEREBRO_PATH: str = ""

    # ─── Web Push (VAPID) ────────────────────────────────────
    VAPID_PRIVATE_KEY: str = ""
    VAPID_PUBLIC_KEY: str = ""
    VAPID_EMAIL: str = "mailto:admin@autopost.com.br"

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
