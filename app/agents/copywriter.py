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
MAX_TOKENS = 1500
MAX_CAPTION_LONG_CHARS = 400
MAX_CAPTION_SHORT_CHARS = 150
MAX_CAPTION_STORIES_CHARS = 100

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

# Abordagem forçada por tentativa de retry — garante variação real
_RETRY_APPROACHES = {
    1: (
        "ABORDAGEM DESTA TENTATIVA: Foco total no RESULTADO e no benefício para o cliente. "
        "Não descreva o processo — destaque a transformação entregue e o problema resolvido. "
        "Seja direto e objetivo."
    ),
    2: (
        "ABORDAGEM DESTA TENTATIVA: Tom EMOCIONAL e aspiracional. "
        "Foque na conquista, no orgulho do trabalho bem feito, na satisfação do cliente. "
        "Humanize a empresa — mostre as pessoas por trás do serviço."
    ),
    3: (
        "ABORDAGEM DESTA TENTATIVA: Tom TÉCNICO e especialista. "
        "Destaque materiais utilizados, técnicas aplicadas e diferenciais de qualidade. "
        "Escreva como um profissional experiente falando para quem entende do assunto."
    ),
}

CONTENT_TYPE_PROMPTS = {
    "post_simples":    "Post direto apresentando o trabalho. Tom: profissional e claro.",
    "obra_andamento":  "Obra em progresso. Tom: transparência e confiança no processo.",
    "obra_concluida":  "Resultado final entregue. Tom: celebração, orgulho e resultado.",
    "engajamento":     "Post para gerar interação. Tom: pergunta direta, convite à participação.",
    "bastidores":      "Momento humano da equipe. Tom: autêntico, próximo, humanizado.",
    "before_after":    "Antes e depois da transformação. Tom: destaque a mudança, celebre o resultado.",
    "carousel":        "Série de imagens mostrando o trabalho. Tom: narrativa visual, conte a história.",
}

_SYSTEM_PROMPT = """\
Você é um especialista em copywriting para redes sociais de pequenas empresas brasileiras.
Crie 3 variações de legenda para Instagram baseadas EXCLUSIVAMENTE nas informações fornecidas.

REGRAS OBRIGATÓRIAS:
1. NUNCA invente dados, medidas, valores, prazos ou informações não presentes na descrição
2. Use o tom de voz e segmento do cliente fornecidos
3. Inclua emojis relevantes (máximo 5 por variação)
4. As 3 variações devem ter abordagens complementares, não repetir o mesmo texto

Responda EXCLUSIVAMENTE em JSON válido, sem texto fora do JSON:
{
  "caption_long": "<legenda completa com storytelling, máximo 400 chars, sem hashtags>",
  "caption_short": "<versão objetiva e direta, máximo 150 chars, sem hashtags>",
  "caption_stories": "<texto para Stories, tom conversacional e imediato, máximo 100 chars>",
  "hashtags": ["hashtag1", "hashtag2", ...],
  "cta": "<call-to-action específico, ex: Entre em contato pelo link na bio!>",
  "suggested_time": "<HH:MM — melhor horário para publicar para este segmento>"
}

Regras das hashtags:
- Entre 10 e 20 hashtags (aplicam-se às 3 variações)
- Inclua hashtags do nicho (ex: #construcaocivil), da localização (ex: #florianopolis) e gerais (#instagram #brasil)
- Sem o símbolo # no JSON — apenas a palavra
- Todas em minúsculo, sem espaços, sem acentos
"""


_VOICE_TONE_MAP = {
    "formal":    "tom formal, profissional e aspiracional",
    "casual":    "tom descontraído, próximo e direto",
    "technical": "tom técnico, preciso e informativo",
}


async def generate_copy_with_ai(
    analysis_result: dict,
    brand_profile: dict,
    user_content_type: str | None = None,
    user_context: str | None = None,
    voice_tone: str | None = None,
    retry_attempt: int = 0,
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

    # Monta informações da(s) foto(s) — suporte multi-foto
    photos = analysis_result.get("photos")
    if photos:
        descriptions = [p.get("description", "") for p in photos if p.get("description")]
        description = f"Sequência de {len(photos)} fotos: " + "; ".join(descriptions) if descriptions else "Série de fotos do trabalho"
        content_type = analysis_result.get("content_type", "obra_realizada")
        stage = analysis_result.get("stage", "")
    else:
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

    # Injeta intenção do cliente se fornecida
    intent_section = ""
    if user_content_type and user_content_type in CONTENT_TYPE_PROMPTS:
        intent_section = f"\nINTENÇÃO DO CLIENTE: {CONTENT_TYPE_PROMPTS[user_content_type]}"

    # Injeta tom de voz configurado pelo usuário
    effective_tone = _VOICE_TONE_MAP.get(voice_tone or "", "") if voice_tone else ""
    voice_tone_section = ""
    if effective_tone:
        voice_tone_section = f"\n#TOM_DE_VOZ: {effective_tone}"

    # Injeta contexto do usuário (especificação de material, serviço, produto)
    user_context_section = ""
    if user_context and user_context.strip():
        user_context_section = (
            f"\n\nCONTEXTO DO CLIENTE (use para enriquecer — não substitui o que você vê na foto):\n"
            f"{user_context.strip()}"
        )

    # Injeta abordagem forçada para garantir variação real no retry
    retry_section = ""
    if retry_attempt > 0:
        approach = _RETRY_APPROACHES.get(retry_attempt, _RETRY_APPROACHES[3])
        retry_section = f"\n\n{approach}"

    # Campos enriquecidos do analista (novos — podem estar ausentes em posts antigos)
    elementos = analysis_result.get("elementos_visuais", "")
    ambiente = analysis_result.get("ambiente", "")
    nivel = analysis_result.get("nivel_acabamento", "")
    extra_section = ""
    if elementos or ambiente or nivel:
        extra_section = (
            f"\n- Elementos visuais: {elementos or 'não identificados'}"
            f"\n- Ambiente: {ambiente or 'não identificado'}"
            f"\n- Nível de acabamento: {nivel or 'não identificado'}"
        )

    user_message = f"""
Crie uma legenda para este post:

CLIENTE:
- Empresa: {company or segment}
- Segmento: {segment}
- Tom de voz: {tone}
- Cidade: {city or "não informada"}{voice_tone_section}

FOTO:
- Tipo: {content_label}
- Descrição: {description}
- Etapa/detalhe: {stage or "não informado"}{extra_section}{user_context_section}{intent_section}{patterns_section}{retry_section}
"""

    logger.info(f"[copywriter] chamando Claude Sonnet — segment={segment} content_type={content_type} user_intent={user_content_type} user_context={'sim' if user_context else 'não'} voice_tone={voice_tone or 'padrão'} retry_attempt={retry_attempt} patterns={'sim' if patterns else 'não'}")

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
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[-2] if "```" in cleaned[3:] else cleaned[3:]
            cleaned = cleaned.lstrip("json").strip()
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude retornou JSON inválido: {raw[:300]}") from e

    # Backward compat: se Claude retornou formato antigo (só caption)
    if "caption" in result and "caption_long" not in result:
        result["caption_long"] = result["caption"]
        result["caption_short"] = None
        result["caption_stories"] = None

    # Garante campos com defaults
    result.setdefault("caption_long", "")
    result.setdefault("caption_short", None)
    result.setdefault("caption_stories", None)
    result.setdefault("hashtags", [])
    result.setdefault("cta", "Entre em contato pelo link na bio!")
    result.setdefault("suggested_time", _DEFAULT_TIMES.get(segment.lower().strip(), _DEFAULT_TIMES["default"]))

    # Trunca variações nos limites
    if result["caption_long"] and len(result["caption_long"]) > MAX_CAPTION_LONG_CHARS:
        result["caption_long"] = result["caption_long"][:MAX_CAPTION_LONG_CHARS - 3] + "..."
    if result["caption_short"] and len(result["caption_short"]) > MAX_CAPTION_SHORT_CHARS:
        result["caption_short"] = result["caption_short"][:MAX_CAPTION_SHORT_CHARS - 3] + "..."
    if result["caption_stories"] and len(result["caption_stories"]) > MAX_CAPTION_STORIES_CHARS:
        result["caption_stories"] = result["caption_stories"][:MAX_CAPTION_STORIES_CHARS - 3] + "..."

    # caption principal = caption_long (para publicação e retrocompat)
    result["caption"] = result["caption_long"] or ""

    # Normaliza hashtags: remove # se presente, lowercase, sem espaços
    result["hashtags"] = [
        h.lstrip("#").lower().replace(" ", "")
        for h in result["hashtags"]
        if h.strip()
    ]

    logger.info(
        f"[copywriter] caption_long={len(result['caption_long'])} chars "
        f"caption_short={len(result['caption_short'] or '')} chars "
        f"caption_stories={len(result['caption_stories'] or '')} chars "
        f"hashtags={len(result['hashtags'])} "
        f"time={result['suggested_time']}"
    )

    return result
