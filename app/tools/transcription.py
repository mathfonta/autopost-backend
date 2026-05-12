"""
Tool de Transcrição de Áudio — interface estável, provider plugável.

Uso:
    from app.tools.transcription import transcribe_audio
    text = transcribe_audio(audio_bytes)   # retorna str | None

Configuração (Railway → Variables):
    TRANSCRIPTION_PROVIDER=gemini    # padrão — usa GEMINI_API_KEY
    TRANSCRIPTION_PROVIDER=whisper   # alternativa — usa OPENAI_API_KEY

Para trocar de provider: alterar TRANSCRIPTION_PROVIDER no Railway.
O pipeline (analyst.py) não precisa ser modificado.
"""

import logging
import os

logger = logging.getLogger(__name__)


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/mp3") -> str | None:
    """
    Interface estável — transcreve áudio para texto em português.

    Args:
        audio_bytes: Bytes do arquivo de áudio (MP3 recomendado)
        mime_type:   MIME type do áudio (padrão: audio/mp3)

    Returns:
        Texto transcrito ou None se falhar / áudio sem fala
    """
    provider = os.getenv("TRANSCRIPTION_PROVIDER", "gemini").lower()

    if provider == "gemini":
        return _transcribe_gemini(audio_bytes, mime_type)
    elif provider == "whisper":
        return _transcribe_whisper(audio_bytes)
    else:
        logger.warning(f"[transcription] provider '{provider}' desconhecido — usando gemini")
        return _transcribe_gemini(audio_bytes, mime_type)


# ─── Provider: Gemini ────────────────────────────────────────────

def _transcribe_gemini(audio_bytes: bytes, mime_type: str) -> str | None:
    """Transcreve usando Google Gemini 2.5 Flash (suporte nativo a áudio)."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[transcription/gemini] GEMINI_API_KEY não configurada — sem transcrição")
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-05-20",
            contents=[
                "Transcreva o áudio em português do Brasil. "
                "Retorne apenas o texto falado, sem comentários, "
                "sem formatação adicional e sem marcações de tempo.",
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            ],
        )

        text = (response.text or "").strip()
        logger.info(f"[transcription/gemini] {len(text)} chars transcritos")
        return text if text else None

    except Exception as e:
        logger.warning(f"[transcription/gemini] falhou: {e}")
        return None


# ─── Provider: Whisper (OpenAI) ──────────────────────────────────

def _transcribe_whisper(audio_bytes: bytes) -> str | None:
    """Transcreve usando OpenAI Whisper-1."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("[transcription/whisper] OPENAI_API_KEY não configurada — sem transcrição")
        return None

    try:
        import io
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.mp3", io.BytesIO(audio_bytes), "audio/mp3"),
            language="pt",
        )
        text = (transcript.text or "").strip()
        logger.info(f"[transcription/whisper] {len(text)} chars transcritos")
        return text if text else None

    except Exception as e:
        logger.warning(f"[transcription/whisper] falhou: {e}")
        return None
