"""
Agente Analista de Foto — usa Claude Haiku com visão para analisar imagens.

Responsabilidades:
- Avaliar qualidade da foto (good / acceptable / bad)
- Identificar tipo de conteúdo (obra_realizada, antes_depois, dica, promocao)
- Decidir se foto de obra deve ser publicada limpa (publish_clean)
- Retornar descrição textual da imagem para o Copywriter usar
"""

import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile

import anthropic
import httpx

from app.cerebro.reader import read_patterns
from app.config import get_settings

logger = logging.getLogger(__name__)

# Modelo mais barato para análise de imagem — Claude Haiku
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

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
  "description": "<descrição detalhada do que aparece na foto, em português, 4 a 5 frases: o que está sendo feito ou exibido, materiais e elementos visuais identificados, ambiente e iluminação, estado de conclusão do trabalho, e qualquer detalhe relevante para uma legenda de marketing>",
  "elementos_visuais": "<lista separada por vírgulas dos principais elementos visíveis: materiais, objetos, ferramentas, acabamentos, cores predominantes>",
  "ambiente": "interno" | "externo" | "misto",
  "nivel_acabamento": "bruto" | "em_andamento" | "finalizado" | "nao_aplicavel",
  "publish_clean": true | false,
  "stage": "<etapa da obra ou tipo de serviço, ex: acabamento, estrutura, reforma, pintura, etc. Deixe vazio se não aplicável>"
}

Regras:
- publish_clean = true quando for foto de obra/trabalho realizado (texto vai na legenda)
- publish_clean = false quando for dica, promoção ou card informativo
- quality "bad" apenas para fotos claramente inutilizáveis (muito escuras, borradas, irreconhecíveis)
- quality "acceptable" para fotos medianas que ainda podem ser publicadas
- description deve ser rica o suficiente para o copywriter criar uma legenda sem ambiguidade — descreva o que vê, não o que imagina
- Responda apenas o JSON, sem ```json``` ou qualquer outro texto
"""


async def analyze_photo_with_ai(
    photo_url: str,
    brand_profile: dict,
    photo_key: str = "",
    user_context: str | None = None,
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

    context_hint = ""
    if user_context and user_context.strip():
        context_hint = f"\n\nO cliente informa sobre esta foto: \"{user_context.strip()}\"\nUse como dado adicional ao que você pode ver na imagem."

    user_message = f"{context}. Analise esta foto para publicação no Instagram.{patterns_context}{context_hint}"

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
        system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
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
        extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
    )

    raw = message.content[0].text.strip()
    logger.info(f"[analyst] resposta bruta: {raw[:200]}")

    try:
        # Remove markdown code fences se presentes
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[-2] if "```" in cleaned[3:] else cleaned[3:]
            cleaned = cleaned.lstrip("json").strip()
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude retornou JSON inválido: {raw[:300]}") from e

    # Garante campos obrigatórios com defaults seguros
    result.setdefault("quality", "acceptable")
    result.setdefault("quality_reason", "ok")
    result.setdefault("content_type", "obra_realizada")
    result.setdefault("description", "")
    result.setdefault("elementos_visuais", "")
    result.setdefault("ambiente", "externo")
    result.setdefault("nivel_acabamento", "nao_aplicavel")
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


# ─── Análise de Vídeo ────────────────────────────────────────────

_VIDEO_SYSTEM_PROMPT = """\
Você é um especialista em marketing digital para pequenas empresas brasileiras.
Você receberá frames extraídos de um vídeo (Reels ou Story) enviado para publicação no Instagram.
Analise os frames e responda EXCLUSIVAMENTE em JSON válido, sem texto fora do JSON.

Retorne exatamente este formato:
{
  "quality": "good" | "acceptable" | "bad",
  "quality_reason": "dark" | "blurry" | "low_res" | "obstructed" | "ok",
  "content_type": "obra_realizada" | "antes_depois" | "dica" | "promocao" | "outro",
  "description": "<descrição detalhada do que aparece no vídeo, em português, 4 a 5 frases: o que está sendo feito ou exibido, materiais e elementos visuais identificados, ambiente e iluminação, estado de conclusão do trabalho, e qualquer detalhe relevante para uma legenda de marketing>",
  "elementos_visuais": "<lista separada por vírgulas dos principais elementos visíveis: materiais, objetos, ferramentas, acabamentos, cores predominantes>",
  "ambiente": "interno" | "externo" | "misto",
  "nivel_acabamento": "bruto" | "em_andamento" | "finalizado" | "nao_aplicavel",
  "publish_clean": true,
  "stage": "<etapa da obra ou tipo de serviço visível no vídeo>"
}

Regras:
- Os frames representam o início, meio e fim do vídeo — descreva o conteúdo geral
- publish_clean é sempre true para vídeos
- quality "bad" apenas se os frames forem totalmente inutilizáveis (escuros, borrados demais)
- description deve ser rica o suficiente para o copywriter criar uma legenda sem ambiguidade
- Responda apenas o JSON, sem ```json``` ou qualquer outro texto
"""


def _extract_video_frames_sync(video_bytes: bytes, n_frames: int = 3) -> list[bytes]:
    """
    Extrai N frames representativos de um vídeo usando FFmpeg.
    Frames extraídos em 25%, 50% e 75% da duração total.
    Retorna lista de bytes JPEG. Pode retornar lista vazia se FFmpeg falhar.
    """
    import json as _json

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, "input.mp4")
        with open(video_path, "wb") as f:
            f.write(video_bytes)

        # Obtém duração do vídeo
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", video_path],
                capture_output=True, text=True, timeout=15, check=True,
            )
            duration = float(_json.loads(probe.stdout)["format"]["duration"])
        except Exception as e:
            logger.warning(f"[analyst] ffprobe falhou: {e}")
            return []

        if duration <= 0:
            return []

        frames: list[bytes] = []
        for i in range(n_frames):
            # timestamps em 25%, 50%, 75% da duração
            ts = duration * (i + 1) / (n_frames + 1)
            frame_path = os.path.join(tmpdir, f"frame_{i}.jpg")
            try:
                subprocess.run(
                    ["ffmpeg", "-ss", str(ts), "-i", video_path,
                     "-frames:v", "1", "-q:v", "3",
                     "-vf", "scale=768:-1",
                     frame_path],
                    capture_output=True, timeout=15, check=True,
                )
                with open(frame_path, "rb") as f:
                    frames.append(f.read())
            except Exception as e:
                logger.warning(f"[analyst] extração frame {i} falhou (ts={ts:.1f}s): {e}")

        return frames


async def analyze_video_with_ai(
    video_key: str,
    brand_profile: dict,
    content_type: str = "reels",
    user_context: str | None = None,
) -> dict:
    """
    Analisa um vídeo extraindo frames e enviando ao Claude Haiku com visão.

    Args:
        video_key: Chave do vídeo no Cloudflare R2
        brand_profile: Perfil de marca do cliente
        content_type: "reels" | "story"
        user_context: Contexto opcional do cliente sobre o vídeo

    Returns:
        dict com os mesmos campos de analyze_photo_with_ai
    """
    from app.core.storage import download_from_r2

    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    segment = brand_profile.get("segment", "empresa")
    city = brand_profile.get("city", "")
    context_line = f"Cliente: {segment}"
    if city:
        context_line += f" em {city}"

    context_hint = ""
    if user_context and user_context.strip():
        context_hint = (
            f"\n\nO cliente informa sobre este vídeo: \"{user_context.strip()}\"\n"
            "Use como dado adicional ao que você pode ver nos frames."
        )

    user_message = (
        f"{context_line}. Analise estes frames do vídeo para publicação no Instagram "
        f"({content_type}).{context_hint}\n"
        "Os frames representam o início, meio e fim do vídeo."
    )

    # Baixa e extrai frames
    logger.info(f"[analyst-video] baixando vídeo key={video_key[:60]}")
    try:
        video_bytes = await download_from_r2(video_key)
    except Exception as e:
        logger.warning(f"[analyst-video] falha ao baixar vídeo: {e}")
        return _minimal_video_analysis(content_type)

    frames = await asyncio.to_thread(_extract_video_frames_sync, video_bytes)

    if not frames:
        logger.warning("[analyst-video] nenhum frame extraído — usando análise mínima")
        return _minimal_video_analysis(content_type)

    logger.info(f"[analyst-video] {len(frames)} frames extraídos — chamando Claude Haiku")

    # Monta conteúdo multi-imagem
    content: list[dict] = []
    for frame_bytes in frames:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(frame_bytes).decode("utf-8"),
            },
        })
    content.append({"type": "text", "text": user_message})

    message = await client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        timeout=30.0,
        system=[{"type": "text", "text": _VIDEO_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
    )

    raw = message.content[0].text.strip()
    logger.info(f"[analyst-video] resposta bruta: {raw[:200]}")

    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[-2] if "```" in cleaned[3:] else cleaned[3:]
            cleaned = cleaned.lstrip("json").strip()
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"[analyst-video] JSON inválido: {e} — usando análise mínima")
        return _minimal_video_analysis(content_type)

    result.setdefault("quality", "good")
    result.setdefault("quality_reason", "ok")
    result.setdefault("content_type", content_type)
    result.setdefault("description", "Vídeo enviado para publicação.")
    result.setdefault("elementos_visuais", "")
    result.setdefault("ambiente", "nao_aplicavel")
    result.setdefault("nivel_acabamento", "nao_aplicavel")
    result.setdefault("publish_clean", True)
    result.setdefault("stage", "")

    logger.info(
        f"[analyst-video] quality={result['quality']} "
        f"content_type={result['content_type']} "
        f"frames_analisados={len(frames)}"
    )
    return result


def _minimal_video_analysis(content_type: str) -> dict:
    """Fallback quando a análise de vídeo falha."""
    return {
        "quality": "good",
        "quality_reason": "ok",
        "content_type": content_type,
        "description": "Vídeo enviado pelo usuário para publicação.",
        "elementos_visuais": "",
        "ambiente": "nao_aplicavel",
        "nivel_acabamento": "nao_aplicavel",
        "publish_clean": True,
        "stage": "",
    }
