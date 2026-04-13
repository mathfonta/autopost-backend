"""
AutoPost API — Ponto de entrada principal.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.api.health import router as health_router

settings = get_settings()

# ─── Rate Limiter ────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
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
        "http://localhost:3000",           # Next.js dev
        "https://*.vercel.app",            # Vercel preview
        "https://autopost.com.br",         # Produção (ajustar)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────
app.include_router(health_router, tags=["infra"])
