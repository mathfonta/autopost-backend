"""
Agente Scout — sintetiza um ScoutReport a partir dos posts reais do cliente
(Epic 22, Story 22.2). Combina uma passada de visão (Claude Haiku / Gemini
Flash, reusando o provider de app/agents/analyst.py) com uma síntese de
raciocínio em Claude Sonnet (baixo volume, alta qualidade — ADR de
roteamento de modelos).

Uso:
    from app.agents.scout import analyze_profile
    report = await analyze_profile(media, brand_profile)
    # report é um ScoutReport (dict) ou None se não houver mídia analisável
    # ou a síntese falhar — nunca levanta exceção.

Esta função não persiste nem dispara nada — produz o ScoutReport em memória.
Persistência, merge no brand_profile e disparo assíncrono são da Story 22.3.
"""

import base64
import json
import logging

import anthropic
import httpx

from app.agents.analyst import (
    _call_gemini_vision,
    _compress_image_for_claude,
    _resolve_analyst_provider,
)
from app.config import get_settings
from app.core.ai_parsing import strip_json_fences

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"  # síntese/raciocínio — mesmo modelo de app/agents/onboarding.py
VISION_MODEL = "claude-haiku-4-5-20251001"  # análise visual — mesmo modelo de app/agents/analyst.py
VISION_SAMPLE_SIZE = 6  # sub-amostra para a chamada de visão (custo de token); legendas usam todos os posts
MAX_TOKENS = 1024

FIXED_SEGMENTS = [
    "construção civil", "arquitetura", "saúde", "dentista",
    "advogado", "contador", "comércio", "outro",
]

_VISUAL_PROMPT = """\
Você é um especialista em marketing digital analisando o feed do Instagram de uma pequena empresa brasileira.
Vai receber algumas fotos recentes publicadas no perfil.

Descreva em texto corrido, 4 a 6 frases:
- o estilo visual predominante (cores, luz, composição, materiais, ambiente)
- o tipo de trabalho, produto ou serviço que aparece com mais frequência
- qualquer padrão visual notável entre as fotos

Responda apenas com a descrição em português, sem introduções nem marcadores. Não invente — descreva só o que vê nas imagens."""

_SYNTHESIS_PROMPT_TEMPLATE = """\
Você é um especialista em marketing digital para pequenas empresas brasileiras.

Um cliente conectou o Instagram à nossa plataforma. Analise os dados reais do perfil dele abaixo e gere um relatório
estruturado sobre o nicho e o estilo reais do negócio — baseado no que ele de fato publica, não em suposições.

DADOS DO PERFIL:
- Segmento declarado pelo cliente: {segment}
- Nome da empresa: {company_name}
- Quantidade de posts analisados: {post_count}

LEGENDAS RECENTES:
{captions_block}

ANÁLISE VISUAL DAS FOTOS:
{visual_description}

SEGMENTOS DISPONÍVEIS NA PLATAFORMA: {fixed_segments}

Responda APENAS com JSON válido, sem texto fora do JSON, neste formato exato:
{{
  "refined_niche": "string — nicho real inferido dos posts, específico (ex: 'móveis planejados sob medida')",
  "recurring_topics": ["string", "..."],
  "visual_style": "string — estilo visual predominante observado",
  "audience_notes": "string — público inferido a partir do conteúdo e tom",
  "suggested_segment": "um dos SEGMENTOS DISPONÍVEIS acima, OU null",
  "confidence": 0.0
}}

Regras:
- suggested_segment: preencha SOMENTE se o nicho real divergir claramente do segmento declarado E um dos segmentos disponíveis descrever melhor o negócio. Caso contrário, retorne null. Nunca invente um segmento fora da lista.
- confidence: entre 0.0 e {confidence_ceiling} — SOMENTE {post_count} posts foram analisados, então seja conservador quanto maior a incerteza.
- Não invente informações que não aparecem nas legendas ou na análise visual.
- Responda apenas o JSON, sem texto adicional, sem ```json```.
"""


# ─── Análise visual ──────────────────────────────────────────────────────────

def _image_url_for(item: dict) -> str | None:
    """Resolve a URL de imagem utilizável de um post. Vídeo usa thumbnail_url —
    media_url de vídeo é o arquivo de vídeo, não uma imagem."""
    if item.get("media_type") == "VIDEO":
        return item.get("thumbnail_url")
    return item.get("media_url") or item.get("thumbnail_url")


def _pick_visual_candidates(media: list[dict], sample_size: int) -> list[str]:
    """Seleciona até `sample_size` URLs de imagem utilizáveis. Posts sem URL
    utilizável (ex.: CAROUSEL_ALBUM sem media_url no nível superior) são
    pulados aqui — a legenda deles ainda entra na síntese textual."""
    urls: list[str] = []
    for item in media:
        url = _image_url_for(item)
        if url:
            urls.append(url)
        if len(urls) >= sample_size:
            break
    return urls


async def _download_image(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning(f"[scout] falha ao baixar imagem para análise visual: {e}")
        return None


async def _analyze_visual_sample(media: list[dict]) -> str | None:
    """Roda uma única chamada de visão multi-imagem sobre uma sub-amostra dos
    posts. Retorna None (sem abortar a análise) se não houver imagem
    utilizável ou a chamada de visão falhar — a síntese segue só com texto."""
    candidate_urls = _pick_visual_candidates(media, VISION_SAMPLE_SIZE)
    if not candidate_urls:
        logger.info("[scout] nenhuma imagem utilizável na amostra — análise segue só com texto")
        return None

    images: list[tuple[bytes, str]] = []
    for url in candidate_urls:
        raw = await _download_image(url)
        if raw is None:
            continue
        images.append(_compress_image_for_claude(raw))

    if not images:
        logger.warning("[scout] todas as imagens da amostra falharam ao baixar — análise segue só com texto")
        return None

    settings = get_settings()
    provider = _resolve_analyst_provider(settings)

    try:
        if provider == "gemini":
            description = await _call_gemini_vision(
                _VISUAL_PROMPT, "Analise estas fotos.", images=images
            )
        else:
            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            content: list[dict] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(img_bytes).decode("utf-8"),
                    },
                }
                for img_bytes, media_type in images
            ]
            content.append({"type": "text", "text": "Analise estas fotos."})
            message = await client.messages.create(
                model=VISION_MODEL,
                max_tokens=512,
                timeout=30.0,
                system=[{"type": "text", "text": _VISUAL_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
            )
            description = message.content[0].text.strip()
    except Exception as e:
        logger.warning(f"[scout] falha na análise visual: {e} — síntese seguirá só com texto")
        return None

    logger.info(f"[scout] análise visual concluída — {len(images)} imagens, provider={provider}")
    return description or None


# ─── Síntese (Claude Sonnet) ─────────────────────────────────────────────────

def _confidence_ceiling(post_count: int) -> float:
    """Teto determinístico de confidence por volume de sinal (AC6 — híbrido).
    O modelo reporta seu próprio valor, mas o código nunca deixa passar
    acima deste teto, independente do que o modelo disser."""
    if post_count < 3:
        return 0.3
    if post_count < 6:
        return 0.6
    return 1.0


def _build_captions_block(media: list[dict]) -> str:
    lines = [f"- {caption}" for item in media if (caption := (item.get("caption") or "").strip())]
    return "\n".join(lines) if lines else "(nenhuma legenda disponível)"


async def _synthesize_report(
    media: list[dict],
    visual_description: str | None,
    brand_profile: dict,
) -> dict:
    settings = get_settings()
    post_count = len(media)
    ceiling = _confidence_ceiling(post_count)

    prompt = _SYNTHESIS_PROMPT_TEMPLATE.format(
        segment=brand_profile.get("segment", "não informado"),
        company_name=brand_profile.get("company_name", "não informado"),
        post_count=post_count,
        captions_block=_build_captions_block(media),
        visual_description=visual_description or "(análise visual indisponível para este lote)",
        fixed_segments=", ".join(FIXED_SEGMENTS),
        confidence_ceiling=ceiling,
    )

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    message = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        timeout=30.0,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    report = json.loads(strip_json_fences(raw))

    # Defensivo: garante o contrato do AC1 mesmo se o modelo omitir campos
    report.setdefault("refined_niche", "")
    report.setdefault("recurring_topics", [])
    report.setdefault("visual_style", "")
    report.setdefault("audience_notes", "")
    report.setdefault("suggested_segment", None)
    report.setdefault("confidence", 0.0)

    # Teto de confidence imposto em código, não só pedido no prompt (AC6)
    try:
        reported_confidence = float(report["confidence"])
    except (TypeError, ValueError):
        reported_confidence = 0.0
    report["confidence"] = max(0.0, min(reported_confidence, ceiling))

    # Nunca deixa o modelo "inventar" um segmento fora da lista fixa (AC4)
    if report["suggested_segment"] not in FIXED_SEGMENTS:
        report["suggested_segment"] = None

    return report


# ─── API pública do agente ───────────────────────────────────────────────────

async def analyze_profile(media: list[dict], brand_profile: dict) -> dict | None:
    """
    Analisa os posts do cliente e produz um ScoutReport.

    Args:
        media: lista de posts retornada por fetch_recent_media (Story 22.1).
        brand_profile: perfil declarado do cliente (segment, tone, company_name, city).

    Returns:
        ScoutReport (dict) conforme o contrato do AC1, ou None se não houver
        mídia para analisar ou a síntese final falhar — nunca levanta exceção.
        Uma falha isolada na análise visual não aborta a análise: a síntese
        segue com o sinal textual (legendas) disponível.
    """
    if not media:
        logger.info("[scout] mídia vazia — análise pulada")
        return None

    visual_description = await _analyze_visual_sample(media)

    try:
        report = await _synthesize_report(media, visual_description, brand_profile)
    except Exception as e:
        logger.warning(f"[scout] falha na síntese do relatório: {e}")
        return None

    logger.info(
        f"[scout] relatório gerado — niche={report['refined_niche']!r} "
        f"confidence={report['confidence']} suggested_segment={report['suggested_segment']!r}"
    )
    return report
