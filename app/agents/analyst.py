"""
Agente Analista de Foto — usa Claude Haiku com visão para analisar imagens.

Responsabilidades:
- Avaliar qualidade da foto (good / acceptable / bad)
- Identificar tipo de conteúdo (obra_realizada, antes_depois, dica, promocao)
- Decidir se foto de obra deve ser publicada limpa (publish_clean)
- Retornar descrição textual da imagem para o Copywriter usar
"""

import base64
import json
import logging

import anthropic
import httpx

from app.cerebro.reader import read_patterns
from app.config import get_settings

logger = logging.getLogger(__name__)

# Modelo mais barato para análise de imagem — Claude Haiku
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 300

# Mensagens de erro amigáveis por motivo de reprovação
_QUALITY_MESSAGES = {
    "dark":      "A foto está muito escura. Tente tirar com mais luz natural ou use o flash.",
    "blurry":    "A foto está fora de foco. Tente novamente segurando o celular mais firme.",
    "low_res":   "A foto tem resolução muito baixa. Use a câmera principal do celular.",
    "obstructed":"Algo está na frente da câmera. Verifique se a lente não está tampada.",
    "bad":       "A foto não está adequada para publicação. Tente tirar uma nova foto com boa iluminação e foco.",
}

_SYSTEM_PROMPT = """\
Você é um especialista em marketing digital para pequenas empresas brasileiras.
Analise a imagem enviada e responda EXCLUSIVAMENTE em JSON válido, sem texto fora do JSON.

Retorne exatamente este formato:
{
  "quality": "good" | "acceptable" | "bad",
  "quality_reason": "dark" | "blurry" | "low_res" | "obstructed" | "ok",
  "content_type": "obra_realizada" | "antes_depois" | "dica" | "promocao" | "outro",
  "description": "<descrição objetiva do que aparece na foto, em português, máximo 2 frases>",
  "publish_clean": true | false,
  "stage": "<etapa da obra ou tipo de serviço, ex: acabamento, estrutura, reforma, etc. Deixe vazio se não aplicável>"
}

Regras:
- publish_clean = true quando for foto de obra/trabalho realizado (texto vai na legenda)
- publish_clean = false quando for dica, promoção ou card informativo
- quality "bad" apenas para fotos claramente inutilizáveis (muito escuras, borradas, irreconhecíveis)
- quality "acceptable" para fotos medianas que ainda podem ser publicadas
- Responda apenas o JSON, sem ```json``` ou qualquer outro texto
"""


async def analyze_photo_with_ai(
    photo_url: str,
    brand_profile: dict,
    photo_key: str = "",
) -> dict:
    """
    Analisa uma foto usando Claude Haiku com visão.

    Args:
        photo_url: URL da imagem no Cloudflare R2
        brand_profile: Perfil de marca do cliente (segment, tone, etc.)
        photo_key: Chave do objeto no R2 (preferencial — evita acesso HTTP ao bucket privado)

    Returns:
        dict com: quality, quality_reason, content_type, description,
                  publish_clean, stage, error_message (se quality=bad)

    Raises:
        anthropic.APITimeoutError: se Claude não responder em 30s
        ValueError: se resposta não for JSON válido
    """
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    segment = brand_profile.get("segment", "empresa")
    city = brand_profile.get("city", "")
    context = f"Cliente: {segment}"
    if city:
        context += f" em {city}"

    # Injeta padrões do cérebro local se disponíveis
    patterns = read_patterns()
    patterns_context = ""
    if patterns:
        patterns_context = (
            f"\n\nPadrões de desempenho descobertos para este cliente:\n{patterns}\n"
            "Use esses padrões para contextualizar sua análise quando relevante."
        )

    user_message = f"{context}. Analise esta foto para publicação no Instagram.{patterns_context}"

    logger.info(
        f"[analyst] chamando Claude Haiku — url={photo_url[:60]}... "
        f"patterns={'sim' if patterns else 'não'}"
    )

    # Baixa a imagem via R2 (boto3) se tiver photo_key, senão tenta HTTP
    if photo_key:
        from app.core.storage import download_from_r2
        img_bytes = await download_from_r2(photo_key)
    else:
        async with httpx.AsyncClient(timeout=30.0) as http:
            img_resp = await http.get(photo_url)
        img_resp.raise_for_status()
        img_bytes = img_resp.content
    img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
    media_type = "image/jpeg"

    message = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        timeout=30.0,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_message,
                    },
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()
    logger.info(f"[analyst] resposta bruta: {raw[:200]}")

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude retornou JSON inválido: {raw[:300]}") from e

    # Garante campos obrigatórios com defaults seguros
    result.setdefault("quality", "acceptable")
    result.setdefault("quality_reason", "ok")
    result.setdefault("content_type", "obra_realizada")
    result.setdefault("description", "")
    result.setdefault("publish_clean", True)
    result.setdefault("stage", "")

    # Adiciona mensagem amigável se foto reprovada
    if result["quality"] == "bad":
        reason = result.get("quality_reason", "bad")
        result["error_message"] = _QUALITY_MESSAGES.get(reason, _QUALITY_MESSAGES["bad"])

    logger.info(
        f"[analyst] quality={result['quality']} "
        f"content_type={result['content_type']} "
        f"publish_clean={result['publish_clean']}"
    )

    return result
