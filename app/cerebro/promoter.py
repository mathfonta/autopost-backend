"""
Motor de Promoção — eleva padrões do cérebro local para o cérebro global.
Chamado pelo Celery Beat na primeira segunda de cada mês às 09:00.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from app.cerebro.reader import get_cerebro_path
from app.config import get_settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2000
_MIN_LOCAL_CONTENT = 200  # mínimo de chars para valer a promoção

_GLOBAL_FALLBACK = Path(r"C:\Users\Matheus\OneDrive\Obsidian\🌐 Global")


def get_global_cerebro_path() -> Path:
    """
    Retorna o path do cérebro global.
    Prioridade: env var GLOBAL_CEREBRO_PATH → fallback OneDrive/Obsidian.
    """
    env_path = os.getenv("GLOBAL_CEREBRO_PATH")
    if env_path:
        return Path(env_path)
    return _GLOBAL_FALLBACK


_SYSTEM_PROMPT = """\
Você é um analista de marketing digital e engenharia de software.
Recebe padrões descobertos em um projeto específico e deve:

1. Classificar cada padrão como:
   - "universal": funciona independente de segmento, plataforma ou audiência
   - "nicho": funciona especificamente para o segmento informado
   - "local": específico deste cliente, não generalizável

2. Gerar um sumário mensal do projeto

3. Identificar lições técnicas não-óbvias (opcional — só se realmente relevante)

Responda EXCLUSIVAMENTE em JSON válido:
{
  "patterns": [
    {"pattern": "<descrição concisa do padrão>", "type": "universal|nicho|local", "confidence": 0.0-1.0}
  ],
  "monthly_summary": "<2-3 frases sobre o desempenho do projeto no mês>",
  "technical_lessons": ["<lição técnica>"]
}

Regras:
- "technical_lessons" pode ser lista vazia [] se não houver lições não-óbvias
- Confidence >= 0.7 para padrões que valem a pena ser promovidos
- Seja conservador: prefira "local" quando houver dúvida
- NUNCA invente padrões — só classifique o que está nos dados
"""


def _ensure_global_structure(global_path: Path) -> None:
    """Garante que a estrutura mínima do cérebro global existe."""
    (global_path / "projetos").mkdir(parents=True, exist_ok=True)

    padroes_file = global_path / "PADROES_GLOBAIS.md"
    if not padroes_file.exists():
        padroes_file.write_text(
            "# Padrões Globais\n\n"
            "> Atualizado automaticamente pelo Motor de Promoção\n\n"
            "## Universal\n\n*(sem dados ainda)*\n",
            encoding="utf-8",
        )

    aprendizados_file = global_path / "APRENDIZADOS.md"
    if not aprendizados_file.exists():
        aprendizados_file.write_text(
            "# Aprendizados\n\n"
            "> Descobertas técnicas e de negócio cross-projeto\n\n",
            encoding="utf-8",
        )


def _build_patterns_section(
    existing: str,
    new_patterns: list[dict],
    project_name: str,
    segment: str,
    timestamp: str,
) -> str:
    """
    Faz merge dos padrões novos no conteúdo existente de PADROES_GLOBAIS.md.
    Estratégia simples: adiciona seções sem duplicar linhas idênticas.
    """
    universal = [p for p in new_patterns if p["type"] == "universal" and p["confidence"] >= 0.7]
    nicho = [p for p in new_patterns if p["type"] == "nicho" and p["confidence"] >= 0.7]

    if not universal and not nicho:
        return existing

    additions = []

    if universal:
        new_universal = [
            f"- {p['pattern']} *(confiança: {p['confidence']:.0%})*"
            for p in universal
            if f"- {p['pattern']}" not in existing  # evita duplicatas exatas
        ]
        if new_universal:
            additions.append(f"\n### Universal — [{project_name}, {timestamp}]\n")
            additions.extend(new_universal)

    if nicho:
        new_nicho = [
            f"- {p['pattern']} *(confiança: {p['confidence']:.0%})*"
            for p in nicho
            if f"- {p['pattern']}" not in existing
        ]
        if new_nicho:
            additions.append(f"\n## {segment.title()} — [{project_name}, {timestamp}]\n")
            additions.extend(new_nicho)

    if not additions:
        return existing  # Tudo já existia ou sem padrões novos

    return existing.rstrip() + "\n\n" + "\n".join(additions) + "\n"


async def promote_to_global(
    project_name: str = "autopost",
    segment: str = "construção civil",
    local_path: Path | None = None,
    global_path: Path | None = None,
) -> None:
    """
    Lê PADROES.md e INSIGHTS.md do projeto, classifica padrões via Claude
    e promove os universais/nicho para o cérebro global.

    Args:
        project_name: Nome do projeto (usado como fonte nos registros)
        segment: Segmento do cliente principal (usado para classificação nicho)
        local_path: Path do cérebro local (default: get_cerebro_path())
        global_path: Path do cérebro global (default: get_global_cerebro_path())
    """
    local_path = local_path or get_cerebro_path()
    global_path = global_path or get_global_cerebro_path()

    # Lê conteúdo local
    padroes_file = local_path / "PADROES.md"
    insights_file = local_path / "INSIGHTS.md"

    local_content = ""
    for f in [padroes_file, insights_file]:
        if f.exists():
            text = f.read_text(encoding="utf-8").strip()
            if len(text) > 50:
                local_content += f"\n\n### {f.name}\n{text}"

    if len(local_content.strip()) < _MIN_LOCAL_CONTENT:
        logger.info(
            "[cerebro.promoter] conteúdo local insuficiente para promoção "
            f"({len(local_content.strip())} chars < {_MIN_LOCAL_CONTENT})"
        )
        return

    # Garante estrutura global
    _ensure_global_structure(global_path)

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_message = (
        f"Projeto: {project_name}\n"
        f"Segmento: {segment}\n\n"
        f"Padrões e insights descobertos:\n{local_content}\n\n"
        "Classifique os padrões e gere o sumário mensal."
    )

    logger.info(f"[cerebro.promoter] classificando padrões de '{project_name}' via Claude")

    message = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        timeout=60.0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude retornou JSON inválido: {raw[:300]}") from exc

    patterns = result.get("patterns", [])
    monthly_summary = result.get("monthly_summary", "")
    technical_lessons = result.get("technical_lessons", [])

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m")

    # ── Atualiza PADROES_GLOBAIS.md ──────────────────────────────
    padroes_globais_file = global_path / "PADROES_GLOBAIS.md"
    existing_padroes = padroes_globais_file.read_text(encoding="utf-8")
    updated_padroes = _build_patterns_section(
        existing_padroes, patterns, project_name, segment, timestamp
    )
    if updated_padroes != existing_padroes:
        padroes_globais_file.write_text(updated_padroes, encoding="utf-8")
        promoted = sum(1 for p in patterns if p["type"] in ("universal", "nicho") and p["confidence"] >= 0.7)
        logger.info(f"[cerebro.promoter] {promoted} padrão(ões) promovido(s) para global")
    else:
        logger.info("[cerebro.promoter] nenhum padrão novo para promover (já existentes)")

    # ── Atualiza projetos/{project_name}.md ──────────────────────
    if monthly_summary:
        projeto_file = global_path / "projetos" / f"{project_name}.md"
        existing_projeto = projeto_file.read_text(encoding="utf-8") if projeto_file.exists() else f"# Projeto: {project_name}\n\n"
        entry = f"\n## Sumário {timestamp}\n\n{monthly_summary}\n"
        if entry not in existing_projeto:
            projeto_file.write_text(existing_projeto.rstrip() + "\n" + entry, encoding="utf-8")
            logger.info(f"[cerebro.promoter] sumário de {timestamp} adicionado a projetos/{project_name}.md")

    # ── Atualiza APRENDIZADOS.md (só se houver lições não-óbvias) ─
    if technical_lessons:
        aprendizados_file = global_path / "APRENDIZADOS.md"
        existing_aprendizados = aprendizados_file.read_text(encoding="utf-8")
        lessons_block = f"\n## [{timestamp}] {project_name}\n\n"
        for lesson in technical_lessons:
            lessons_block += f"- {lesson}\n"
        if lessons_block not in existing_aprendizados:
            aprendizados_file.write_text(
                existing_aprendizados.rstrip() + "\n" + lessons_block, encoding="utf-8"
            )
            logger.info(f"[cerebro.promoter] {len(technical_lessons)} lição(ões) adicionada(s) a APRENDIZADOS.md")

    logger.info("[cerebro.promoter] promoção concluída")
