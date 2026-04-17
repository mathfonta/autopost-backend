"""
Agente Copywriter — usa Claude Sonnet para gerar legenda, hashtags e CTA.

Responsabilidades:
- Criar legenda adaptada ao tom de voz e segmento do cliente
- Gerar hashtags: nicho + localização + gerais
- Sugerir CTA específico para o segmento
- Sugerir melhor horário de publicação
- NUNCA inventar dados — só usa o que está na análise da foto
"""

import json
import logging

import anthropic

from app.cerebro.reader import read_patterns
from app.config import get_settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 600
MAX_CAPTION_CHARS = 2200

# Horários de pico por segmento (fallback se Claude não sugerir)
_DEFAULT_TIMES = {
    "construção civil":    "18:00",
    "arquitetura":         "19:00",
    "saúde":               "07:00",
    "advogado":            "08:00",
    "dentista":            "12:00",
    "contador":            "08:00",
    "comércio":            "11:00",
    "default":             "19:00",
}

_SYSTEM_PROMPT = """\
Você é um especialista em copywriting para redes sociais de pequenas empresas brasileiras.
Crie uma legenda para Instagram baseada EXCLUSIVAMENTE nas informações fornecidas.

REGRAS OBRIGATÓRIAS:
1. NUNCA invente dados, medidas, valores, prazos ou informações não presentes na descrição
2. A legenda deve ter no máximo 2200 caracteres
3. Use o tom de voz e segmento do cliente fornecidos
4. Inclua emojis relevantes (máximo 5)
5. Termine com os hashtags fora da legenda principal

Responda EXCLUSIVAMENTE em JSON válido, sem texto fora do JSON:
{
  "caption": "<legenda completa, sem hashtags, máximo 2200 chars>",
  "hashtags": ["hashtag1", "hashtag2", ...],
  "cta": "<call-to-action específico, ex: Entre em contato pelo link na bio!>",
  "suggested_time": "<HH:MM — melhor horário para publicar para este segmento>"
}

Regras das hashtags:
- Entre 10 e 20 hashtags
- Inclua hashtags do nicho (ex: #construcaocivil), da localização (ex: #florianopolis) e gerais (#instagram #brasil)
- Sem o símbolo # no JSON — apenas a palavra
- Todas em minúsculo, sem espaços, sem acentos
"""


async def generate_copy_with_ai(
    analysis_result: dict,
    brand_profile: dict,
) -> dict:
    """
    Gera legenda, hashtags e CTA para o post usando Claude Sonnet.

    Args:
        analysis_result: Output do Agente Analista (description, content_type, stage)
        brand_profile: Perfil de marca do cliente (segment, tone, city, company_name)

    Returns:
        dict com: caption, hashtags, cta, suggested_time

    Raises:
        anthropic.APITimeoutError: se Claude não responder em 30s
        ValueError: se resposta não for JSON válido
    """
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Monta contexto do cliente
    segment = brand_profile.get("segment", "empresa")
    tone = brand_profile.get("tone", "profissional")
    city = brand_profile.get("city", "")
    company = brand_profile.get("company_name", "")

    # Monta informações da foto
    description = analysis_result.get("description", "Foto do trabalho realizado")
    content_type = analysis_result.get("content_type", "obra_realizada")
    stage = analysis_result.get("stage", "")

    content_type_labels = {
        "obra_realizada": "foto de obra/serviço realizado",
        "antes_depois":   "antes e depois de reforma/serviço",
        "dica":           "dica ou conteúdo educativo",
        "promocao":       "promoção ou oferta especial",
        "outro":          "conteúdo diverso",
    }
    content_label = content_type_labels.get(content_type, content_type)

    # Injeta padrões do cérebro local (horário e CTA comprovados)
    patterns = read_patterns()
    patterns_section = ""
    if patterns:
        patterns_section = (
            f"\n\nPADRÕES COMPROVADOS PARA ESTE CLIENTE:\n{patterns}\n\n"
            "Use o horário e CTA sugeridos pelos padrões como referência prioritária."
        )

    user_message = f"""
Crie uma legenda para este post:

CLIENTE:
- Empresa: {company or segment}
- Segmento: {segment}
- Tom de voz: {tone}
- Cidade: {city or "não informada"}

FOTO:
- Tipo: {content_label}
- Descrição: {description}
- Etapa/detalhe: {stage or "não informado"}{patterns_section}
"""

    logger.info(f"[copywriter] chamando Claude Sonnet — segment={segment} content_type={content_type} patterns={'sim' if patterns else 'não'}")

    message = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        timeout=30.0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    logger.info(f"[copywriter] resposta bruta: {raw[:200]}")

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude retornou JSON inválido: {raw[:300]}") from e

    # Garante campos com defaults
    result.setdefault("caption", "")
    result.setdefault("hashtags", [])
    result.setdefault("cta", "Entre em contato pelo link na bio!")
    result.setdefault("suggested_time", _DEFAULT_TIMES.get(segment.lower().strip(), _DEFAULT_TIMES["default"]))

    # Trunca caption se ultrapassar limite do Instagram
    if len(result["caption"]) > MAX_CAPTION_CHARS:
        result["caption"] = result["caption"][:MAX_CAPTION_CHARS - 3] + "..."
        logger.warning("[copywriter] caption truncada para 2200 chars")

    # Normaliza hashtags: remove # se presente, lowercase, sem espaços
    result["hashtags"] = [
        h.lstrip("#").lower().replace(" ", "")
        for h in result["hashtags"]
        if h.strip()
    ]

    logger.info(
        f"[copywriter] caption={len(result['caption'])} chars "
        f"hashtags={len(result['hashtags'])} "
        f"time={result['suggested_time']}"
    )

    return result
