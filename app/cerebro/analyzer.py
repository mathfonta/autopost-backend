"""
Analisa histórico acumulado e atualiza PADROES.md e INSIGHTS.md usando Claude Sonnet.
Chamado pelo Celery Beat toda segunda às 08:00.
"""
import json
import logging
from datetime import datetime, timezone

import anthropic

from app.cerebro.reader import get_cerebro_path
from app.config import get_settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2000
_MIN_HISTORY_LENGTH = 100  # mínimo de chars para valer a análise

_SYSTEM_PROMPT = """\
Você é um analista de marketing digital especializado em Instagram para pequenas empresas brasileiras.
Analise o histórico de posts fornecido e gere dois documentos Markdown.

Responda EXCLUSIVAMENTE em JSON válido com dois campos:
{
  "padroes": "<conteúdo completo de PADROES.md em markdown>",
  "insights": "<conteúdo completo de INSIGHTS.md em markdown>"
}

PADROES.md deve conter seções:
- ## Tipo de Foto com Melhor Desempenho (baseado em curtidas/alcance médio por tipo)
- ## Melhor Horário de Publicação (baseado em dados reais)
- ## CTA Mais Eficaz (qual gerou mais engajamento)
- ## Recomendações para Próxima Semana (3 ações concretas)

INSIGHTS.md deve conter seções:
- ## Resumo da Semana
- ## Total de Posts Analisados
- ## Média de Curtidas
- ## Média de Alcance
- ## Evolução vs Semana Anterior (se dados disponíveis, caso contrário: "Primeira análise")
- ## Próxima Ação Recomendada (1 frase objetiva e acionável)

Regras:
- Use apenas dados do histórico — NUNCA invente métricas
- Se dados insuficientes para um padrão, escreva "Dados insuficientes — continue publicando"
- Seja direto e prático
"""


async def analyze_and_update_patterns() -> None:
    """
    Lê todo historico/*.md, usa Claude Sonnet para extrair padrões,
    atualiza PADROES.md e INSIGHTS.md no cérebro local.
    """
    cerebro_path = get_cerebro_path()
    historico_dir = cerebro_path / "historico"

    if not historico_dir.exists():
        logger.info("[cerebro.analyzer] diretório historico/ não encontrado — nada a analisar")
        return

    historico_files = sorted(
        f for f in historico_dir.glob("*.md") if f.name != ".gitkeep"
    )

    if not historico_files:
        logger.info("[cerebro.analyzer] histórico vazio — aguardando primeiros posts")
        return

    historico_content = "\n\n".join(
        f.read_text(encoding="utf-8") for f in historico_files
    )

    if len(historico_content.strip()) < _MIN_HISTORY_LENGTH:
        logger.info("[cerebro.analyzer] histórico muito curto — aguardando mais dados")
        return

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_message = (
        "Histórico de posts do AutoPost (Instagram para construção civil):\n\n"
        f"{historico_content}\n\n"
        "Gere PADROES.md e INSIGHTS.md conforme as instruções do sistema."
    )

    logger.info(
        f"[cerebro.analyzer] analisando {len(historico_files)} arquivo(s) "
        f"({len(historico_content)} chars)"
    )

    message = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        timeout=60.0,
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message}],
        extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
    )

    raw = message.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude retornou JSON inválido: {raw[:300]}") from exc

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"<!-- Atualizado automaticamente em {timestamp} pelo Celery Beat -->\n\n"

    (cerebro_path / "PADROES.md").write_text(
        header + result["padroes"], encoding="utf-8"
    )
    (cerebro_path / "INSIGHTS.md").write_text(
        header + result["insights"], encoding="utf-8"
    )

    logger.info("[cerebro.analyzer] PADROES.md e INSIGHTS.md atualizados com sucesso")
