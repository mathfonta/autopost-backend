"""
Configuração global de testes.
Define variáveis de ambiente antes de qualquer import do app
para evitar falha de validação do Pydantic Settings.
"""

import os
import pytest

# ─── Env vars mínimas (antes de qualquer import do app) ───────
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-chars-minimum!!")
os.environ.setdefault("CLOUDFLARE_R2_BUCKET", "test-bucket")
os.environ.setdefault("CLOUDFLARE_R2_ACCESS_KEY", "test-access-key")
os.environ.setdefault("CLOUDFLARE_R2_SECRET_KEY", "test-secret-key")
os.environ.setdefault("CLOUDFLARE_R2_ENDPOINT", "https://test.r2.cloudflarestorage.com")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")
# Testes existentes cobrem o path Claude com mocks determinísticos — fixar o
# provider default aqui evita que testes façam chamadas reais à API Gemini
# só porque o .env local (fora do controle da suite) tem GEMINI_API_KEY real.
# Testes dedicados ao path Gemini sobrescrevem isso explicitamente via monkeypatch.
os.environ.setdefault("COPY_PROVIDER", "claude")
os.environ.setdefault("ANALYST_PROVIDER", "claude")
