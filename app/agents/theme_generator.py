"""
ThemeGenerator — gera estrutura de slides para carrossel autônomo via Claude.
"""
import logging
import os
import json

import anthropic

from app.core.ai_parsing import strip_json_fences
from app.data.theme_library import THEME_LIBRARY

logger = logging.getLogger(__name__)

SLIDE_STRUCTURE_PROMPT = """Você é um especialista em conteúdo para Instagram para pequenas e médias empresas brasileiras.

Gere a estrutura de slides para um carrossel do Instagram sobre o tema: "{theme_title}"
Descrição: {theme_description}
Empresa: {company_name}
Segmento: {segment}{scout_context}

REGRAS:
- Primeiro card: título impactante do tema (máx 60 chars)
- Cards intermediários: {n_content_slides} cards com headline + corpo curto (máx 120 chars no corpo)
- Último card: CTA personalizado para a empresa (headline + corpo com convite para contato)
- Tom: profissional mas acessível, direto ao ponto
- Linguagem: português do Brasil

RESPONDA APENAS COM JSON VÁLIDO neste formato exato:
{{
  "title_card": {{
    "headline": "string — título principal do carrossel",
    "subheadline": "string — subtítulo opcional (máx 60 chars)"
  }},
  "content_slides": [
    {{
      "number": 1,
      "headline": "string — título do slide (máx 60 chars)",
      "body": "string — explicação (máx 120 chars)"
    }}
  ],
  "cta_card": {{
    "headline": "string — CTA direto (máx 60 chars)",
    "body": "string — convite para ação (máx 100 chars)"
  }}
}}"""


async def generate_slide_structure(
    theme_id: str,
    brand_profile: dict,
) -> dict:
    """
    Gera estrutura de slides para um carrossel autônomo.

    Returns:
        dict com title_card, content_slides[], cta_card
    Raises:
        ValueError se o tema não for encontrado
        RuntimeError se o Claude falhar após retries
    """
    # Localiza o tema na biblioteca
    theme = None
    for segment_themes in THEME_LIBRARY.values():
        for t in segment_themes:
            if t["id"] == theme_id:
                theme = t
                break
        if theme:
            break

    if not theme:
        raise ValueError(f"Tema '{theme_id}' não encontrado na biblioteca")

    company_name = brand_profile.get("company_name", "nossa empresa")
    segment = brand_profile.get("segment", "serviços")
    n_content_slides = theme["slide_count"] - 2  # -1 título -1 CTA

    # Insights do Agente Scout (Epic 22, Story 22.4) — enriquece a geração
    # quando disponíveis; string vazia (sem mudança de comportamento) caso
    # contrário. Defensivo: scout_insights ausente/parcial/malformado nunca quebra.
    scout_insights = brand_profile.get("scout_insights") or {}
    scout_context = ""
    if isinstance(scout_insights, dict) and scout_insights:
        refined_niche = scout_insights.get("refined_niche") or ""
        recurring_topics = scout_insights.get("recurring_topics") or []
        scout_lines = []
        if refined_niche:
            scout_lines.append(f"Nicho real observado nos posts: {refined_niche}")
        if isinstance(recurring_topics, list) and recurring_topics:
            scout_lines.append(f"Temas recorrentes no perfil: {', '.join(str(t) for t in recurring_topics)}")
        if scout_lines:
            scout_context = (
                "\n" + "\n".join(scout_lines)
                + "\nConsidere esse contexto real ao adaptar a linguagem do carrossel para esta empresa."
            )

    prompt = SLIDE_STRUCTURE_PROMPT.format(
        theme_title=theme["title"],
        theme_description=theme["description"],
        company_name=company_name,
        segment=segment,
        scout_context=scout_context,
        n_content_slides=n_content_slides,
    )

    logger.info(f"[theme_generator] gerando estrutura para theme_id={theme_id}")

    client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    message = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = strip_json_fences(message.content[0].text.strip())

    try:
        structure = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[theme_generator] JSON inválido: {e}\nRaw: {raw[:500]}")
        raise RuntimeError(f"Claude retornou JSON inválido: {e}")

    # Valida campos obrigatórios
    if "title_card" not in structure or "cta_card" not in structure:
        raise RuntimeError("Estrutura de slides incompleta — campos obrigatórios ausentes")
    if "content_slides" not in structure or not structure["content_slides"]:
        raise RuntimeError("Estrutura de slides incompleta — content_slides vazio")

    logger.info(
        f"[theme_generator] estrutura gerada: "
        f"{len(structure['content_slides'])} slides de conteúdo"
    )
    return structure
