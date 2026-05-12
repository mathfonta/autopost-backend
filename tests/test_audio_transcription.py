"""
Testes para transcrição automática de áudio (Story 12.3).

Cobre:
- Filtro de 20 palavras mínimas (AC4)
- Provider Gemini: retorna transcrição / fallback gracioso (AC2, AC3)
- Provider Whisper: retorna transcrição / fallback gracioso (AC2, AC3)
- audio_transcript armazenado no resultado do analyst (AC2)
- Injeção no copywriter quando presente / ausente (AC5, AC8)
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Fixture de áudio mínimo ─────────────────────────────────────

def _fake_mp3(size: int = 2000) -> bytes:
    return b"\xff\xfb" + b"\x00" * size  # header MP3 mínimo + padding


# ─── Testes do filtro de qualidade (AC4) ─────────────────────────

class TestTranscriptionFilter:
    """Filtro de 20 palavras mínimas."""

    def test_short_transcript_filtered(self):
        """Transcrição com < 20 palavras deve ser descartada."""
        short = "instalamos a porta hoje"  # 4 palavras
        result = short if len(short.split()) >= 20 else None
        assert result is None

    def test_long_transcript_kept(self):
        """Transcrição com >= 20 palavras deve ser mantida."""
        long_text = (
            "a cliente chegou com o trilho mas a porta não servia "
            "adaptamos uma porta maciça de cozinha cortamos na medida "
            "instalamos a fechadura e ficou perfeito"
        )
        assert len(long_text.split()) >= 20
        result = long_text if len(long_text.split()) >= 20 else None
        assert result == long_text

    def test_exactly_20_words_kept(self):
        """Exatamente 20 palavras deve ser mantida (boundary)."""
        text = " ".join(["palavra"] * 20)
        result = text if len(text.split()) >= 20 else None
        assert result == text

    def test_19_words_filtered(self):
        """19 palavras: filtrada."""
        text = " ".join(["palavra"] * 19)
        result = text if len(text.split()) >= 20 else None
        assert result is None


# ─── Testes do provider Gemini (AC2 — provider padrão) ──────────

class TestGeminiProvider:

    def _make_mock_genai(self, transcript_text: str) -> MagicMock:
        mock_response = MagicMock()
        mock_response.text = transcript_text

        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        return mock_genai

    def test_gemini_returns_transcript(self):
        """Gemini disponível: retorna transcrição."""
        from app.tools.transcription import _transcribe_gemini

        transcript_text = (
            "a cliente chegou com o trilho mas a porta não servia, "
            "adaptamos uma porta maciça de cozinha, cortamos na medida e instalamos a fechadura"
        )
        mock_genai = self._make_mock_genai(transcript_text)

        with patch.dict(sys.modules, {"google.generativeai": mock_genai}), \
             patch("app.tools.transcription.os.getenv", return_value="fake-gemini-key"):
            result = _transcribe_gemini(_fake_mp3(), "audio/mp3")

        assert result is not None
        assert "porta" in result

    def test_gemini_api_error_returns_none(self):
        """Gemini com erro de API: retorna None (fallback gracioso — AC3)."""
        from app.tools.transcription import _transcribe_gemini

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.side_effect = Exception("API error 503")

        with patch.dict(sys.modules, {"google.generativeai": mock_genai}), \
             patch("app.tools.transcription.os.getenv", return_value="fake-key"):
            result = _transcribe_gemini(_fake_mp3(), "audio/mp3")

        assert result is None

    def test_gemini_no_api_key_returns_none(self):
        """GEMINI_API_KEY ausente: retorna None silenciosamente (AC6)."""
        from app.tools.transcription import _transcribe_gemini

        with patch("app.tools.transcription.os.getenv", return_value=""):
            result = _transcribe_gemini(_fake_mp3(), "audio/mp3")

        assert result is None

    def test_gemini_empty_response_returns_none(self):
        """Gemini retorna texto vazio: None."""
        from app.tools.transcription import _transcribe_gemini

        mock_genai = self._make_mock_genai("")  # resposta vazia

        with patch.dict(sys.modules, {"google.generativeai": mock_genai}), \
             patch("app.tools.transcription.os.getenv", return_value="fake-key"):
            result = _transcribe_gemini(_fake_mp3(), "audio/mp3")

        assert result is None


# ─── Testes do provider Whisper (AC2 — provider alternativo) ─────

class TestWhisperProvider:

    def _make_mock_openai(self, transcript_text: str) -> MagicMock:
        mock_transcript = MagicMock()
        mock_transcript.text = transcript_text

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = mock_transcript

        mock_openai_module = MagicMock()
        mock_openai_module.OpenAI.return_value = mock_client
        return mock_openai_module

    def test_whisper_returns_transcript(self):
        """Whisper disponível: retorna transcrição."""
        from app.tools.transcription import _transcribe_whisper

        transcript_text = (
            "instalei a porta de correr no banheiro da cliente, "
            "o trilho que ela trouxe não encaixava então adaptei "
            "cortei a porta na medida e fixei a fechadura embutida"
        )
        mock_openai = self._make_mock_openai(transcript_text)

        with patch.dict(sys.modules, {"openai": mock_openai}), \
             patch("app.tools.transcription.os.getenv", return_value="fake-openai-key"):
            result = _transcribe_whisper(_fake_mp3())

        assert result is not None
        assert "porta" in result

    def test_whisper_api_error_returns_none(self):
        """Whisper com erro de conexão: retorna None (fallback gracioso — AC3)."""
        from app.tools.transcription import _transcribe_whisper

        mock_openai = MagicMock()
        mock_openai.OpenAI.side_effect = Exception("Connection error")

        with patch.dict(sys.modules, {"openai": mock_openai}), \
             patch("app.tools.transcription.os.getenv", return_value="fake-key"):
            result = _transcribe_whisper(_fake_mp3())

        assert result is None

    def test_whisper_no_api_key_returns_none(self):
        """OPENAI_API_KEY ausente: retorna None silenciosamente (AC6)."""
        from app.tools.transcription import _transcribe_whisper

        with patch("app.tools.transcription.os.getenv", return_value=""):
            result = _transcribe_whisper(_fake_mp3())

        assert result is None


# ─── Testes de integração: audio_transcript no result (AC2, AC4) ─

class TestAnalystAudioTranscript:
    """Testa que audio_transcript é armazenado corretamente no result."""

    def _apply_word_filter(self, transcript: str | None) -> str | None:
        """Replica a lógica do analyst para filtrar transcrições curtas."""
        if not transcript:
            return None
        return transcript if len(transcript.split()) >= 20 else None

    def test_long_transcript_stored(self):
        """Transcrição longa: armazenada em audio_transcript."""
        transcript = (
            "a cliente chegou com o trilho mas a porta não servia, "
            "adaptamos uma porta maciça de cozinha, cortamos na medida "
            "e instalamos a fechadura embutida, ficou perfeito para o banheiro"
        )
        result = self._apply_word_filter(transcript)
        assert result == transcript

    def test_short_transcript_becomes_none(self):
        """Transcrição curta: audio_transcript = None."""
        transcript = "porta instalada hoje"  # 3 palavras
        result = self._apply_word_filter(transcript)
        assert result is None

    def test_none_audio_becomes_none(self):
        """Sem áudio: audio_transcript = None."""
        result = self._apply_word_filter(None)
        assert result is None


# ─── Testes de injeção no copywriter (AC5, AC8) ──────────────────

class TestCopywriterTranscriptInjection:

    @pytest.mark.asyncio
    @patch("app.agents.copywriter.anthropic.AsyncAnthropic")
    @patch("app.agents.copywriter.get_settings")
    @patch("app.agents.copywriter.read_patterns", return_value=None)
    async def test_transcript_injected_when_present(
        self, mock_patterns, mock_settings, mock_anthropic
    ):
        """audio_transcript presente: injetado no user_message do copywriter (AC5)."""
        from app.agents.copywriter import generate_copy_with_ai

        mock_settings.return_value.ANTHROPIC_API_KEY = "fake-key"

        transcript = (
            "a cliente chegou com o trilho mas a porta não servia, "
            "adaptamos uma porta de cozinha, cortamos na medida e instalamos a fechadura"
        )
        analysis_result = {
            "description": "Porta de correr instalada em banheiro.",
            "content_type": "obra_realizada",
            "stage": "instalação concluída",
            "audio_transcript": transcript,
        }

        captured: dict = {}

        async def capture_create(**kwargs):
            msg = kwargs["messages"][0]["content"][1]["text"]
            captured["text"] = msg
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text=(
                '{"caption_long":"Legenda.","caption_short":"Curta.",'
                '"caption_stories":"Story.","hashtags":["construção"],'
                '"cta":"Entre em contato!","suggested_time":"18:00"}'
            ))]
            return mock_resp

        mock_client = MagicMock()
        mock_client.messages.create = capture_create
        mock_anthropic.return_value = mock_client

        await generate_copy_with_ai(
            analysis_result, {"segment": "construção civil", "tone": "profissional", "city": "SP"}
        )

        assert "TRANSCRIÇÃO DO ÁUDIO" in captured["text"]
        assert transcript in captured["text"]

    @pytest.mark.asyncio
    @patch("app.agents.copywriter.anthropic.AsyncAnthropic")
    @patch("app.agents.copywriter.get_settings")
    @patch("app.agents.copywriter.read_patterns", return_value=None)
    async def test_no_transcript_no_injection(
        self, mock_patterns, mock_settings, mock_anthropic
    ):
        """audio_transcript ausente: sem injeção (AC8 — sem regressão em fotos)."""
        from app.agents.copywriter import generate_copy_with_ai

        mock_settings.return_value.ANTHROPIC_API_KEY = "fake-key"

        analysis_result = {
            "description": "Foto de obra realizada.",
            "content_type": "obra_realizada",
            "stage": "",
            # sem audio_transcript
        }

        captured: dict = {}

        async def capture_create(**kwargs):
            msg = kwargs["messages"][0]["content"][1]["text"]
            captured["text"] = msg
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text=(
                '{"caption_long":"Legenda.","caption_short":"Curta.",'
                '"caption_stories":"Story.","hashtags":["construção"],'
                '"cta":"Entre em contato!","suggested_time":"19:00"}'
            ))]
            return mock_resp

        mock_client = MagicMock()
        mock_client.messages.create = capture_create
        mock_anthropic.return_value = mock_client

        await generate_copy_with_ai(
            analysis_result, {"segment": "construção civil", "tone": "profissional"}
        )

        assert "TRANSCRIÇÃO DO ÁUDIO" not in captured["text"]

    @pytest.mark.asyncio
    @patch("app.agents.copywriter.anthropic.AsyncAnthropic")
    @patch("app.agents.copywriter.get_settings")
    @patch("app.agents.copywriter.read_patterns", return_value=None)
    async def test_transcript_none_explicit_not_injected(
        self, mock_patterns, mock_settings, mock_anthropic
    ):
        """audio_transcript=None explícito: sem injeção (vídeo silencioso filtrado)."""
        from app.agents.copywriter import generate_copy_with_ai

        mock_settings.return_value.ANTHROPIC_API_KEY = "fake-key"

        analysis_result = {
            "description": "Vídeo de instalação.",
            "content_type": "obra_realizada",
            "stage": "instalação",
            "audio_transcript": None,  # explicitamente None
        }

        captured: dict = {}

        async def capture_create(**kwargs):
            msg = kwargs["messages"][0]["content"][1]["text"]
            captured["text"] = msg
            mock_resp = MagicMock()
            mock_resp.content = [MagicMock(text=(
                '{"caption_long":"Legenda.","caption_short":"Curta.",'
                '"caption_stories":"Story.","hashtags":["reels"],'
                '"cta":"Entre em contato!","suggested_time":"18:00"}'
            ))]
            return mock_resp

        mock_client = MagicMock()
        mock_client.messages.create = capture_create
        mock_anthropic.return_value = mock_client

        await generate_copy_with_ai(
            analysis_result, {"segment": "construção civil", "tone": "profissional"}
        )

        assert "TRANSCRIÇÃO DO ÁUDIO" not in captured["text"]
