"""
AutoPost API — Ponto de entrada principal.
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.core.limiter import limiter
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.onboarding import router as onboarding_router
from app.api.content import router as content_router
from app.api.meta import router as meta_router
from app.api.push import router as push_router

settings = get_settings()


def _run_migrations() -> None:
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup — aplica migrations pendentes (idempotente)
    try:
        await asyncio.to_thread(_run_migrations)
        print("✅ Migrations aplicadas")
    except Exception as exc:
        print(f"⚠️  Erro ao aplicar migrations: {exc}")
    print(f"🚀 AutoPost API v{settings.APP_VERSION} iniciando [{settings.ENV}]")
    yield
    # Shutdown
    print("👋 AutoPost API encerrando")


# ─── App ─────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENV == "development" else None,
    redoc_url=None,
)

# ─── Middleware ───────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://autopost.com.br",
        "https://autopost.app.br",
        "https://autopost-frontend-one.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# ─── Routers ─────────────────────────────────────────────────
app.include_router(health_router, tags=["infra"])
app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(content_router)
app.include_router(meta_router)
app.include_router(push_router)
