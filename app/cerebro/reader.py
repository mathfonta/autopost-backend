"""
Lê padrões do cérebro local para injetar como contexto nos agentes.
"""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_MIN_CONTENT_LENGTH = 50  # abaixo disso, arquivo ainda não tem dados reais


def get_cerebro_path() -> Path:
    """
    Retorna o path do cérebro local.
    Prioridade: env var CEREBRO_PATH → fallback .cerebro-autopost/ na raiz do projeto.
    """
    env_path = os.getenv("CEREBRO_PATH")
    if env_path:
        return Path(env_path)
    # Fallback: sobe 4 níveis de app/cerebro/reader.py → raiz do projeto
    return Path(__file__).parent.parent.parent.parent / ".cerebro-autopost"


def read_patterns() -> str | None:
    """
    Lê PADROES.md do cérebro local.

    Returns:
        Conteúdo do arquivo se tiver dados reais (>= 50 chars),
        None se arquivo não existe, está vazio ou ainda sem dados.
    """
    try:
        padroes_path = get_cerebro_path() / "PADROES.md"
        if not padroes_path.exists():
            return None
        content = padroes_path.read_text(encoding="utf-8").strip()
        if len(content) < _MIN_CONTENT_LENGTH:
            return None
        # Arquivo template ainda não tem dados reais
        if "a descobrir" in content and "Gerado por Claude" not in content:
            return None
        return content
    except Exception as exc:
        logger.warning(f"[cerebro.reader] falha ao ler padrões: {exc}")
        return None
