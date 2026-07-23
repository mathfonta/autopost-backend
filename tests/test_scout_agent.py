"""
Testes do Agente Scout (Story 22.2) — mock do SDK Anthropic e do download de imagem.
Não chama API real (Instagram, Claude ou Gemini).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.scout import (
    FIXED_SEGMENTS,
    _build_captions_block,
    _confidence_ceiling,
    _image_url_for,
    _pick_visual_candidates,
    analyze_profile,
)

BRAND_PROFILE = {"segment": "comércio", "company_name": "Marcenaria Silva", "city": "Florianópolis"}

MEDIA_SAMPLE = [
    {
        "id": "media-1",
        "caption": "Cozinha planejada finalizada em madeira clara",
        "media_type": "IMAGE",
        "media_url": "https://cdn.example.com/media-1.jpg",
        "thumbnail_url": None,
    },
    {
        "id": "media-2",
        "caption": "Processo de montagem de um guarda-roupa sob medida",
        "media_type": "VIDEO",
        "media_url": "https://cdn.example.com/media-2.mp4",
        "thumbnail_url": "https://cdn.example.com/media-2-thumb.jpg",
    },
    {
        "id": "media-3",
        "caption": "Antes e depois de uma reforma de cozinha",
        "media_type": "CAROUSEL_ALBUM",
        "media_url": None,
        "thumbnail_url": None,
    },
]

VALID_REPORT_JSON = {
    "refined_niche": "móveis planejados sob medida",
    "recurring_topics": ["cozinhas planejadas", "processo de marcenaria"],
    "visual_style": "ambientes finalizados, madeira clara, luz natural",
    "audience_notes": "casais montando o primeiro apartamento",
    "suggested_segment": None,
    "confidence": 0.9,
}


def _mock_text_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = [MagicMock()]
    message.content[0].text = text
    return message


def _mock_json_response(content: dict) -> MagicMock:
    return _mock_text_response(json.dumps(content))


@pytest.fixture(autouse=True)
def _mock_image_download():
    """Todos os testes que chegam à etapa de visão baixam via httpx.AsyncClient.get —
    mocka para rodar offline, mesmo padrão de test_analyst_agent.py."""
    fake_response = MagicMock()
    fake_response.content = b"\xff\xd8\xff" + b"0" * 50  # magic bytes JPEG
    fake_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=fake_response)):
        yield


@pytest.fixture(autouse=True)
def _force_claude_provider():
    """Fixa o provider de visão em 'claude' — determinístico, não depende de
    GEMINI_API_KEY estar setada no ambiente de teste."""
    with patch("app.agents.scout._resolve_analyst_provider", return_value="claude"):
        yield


# ─── analyze_profile: caminho feliz e casos exigidos pelo AC8 ───────────────

@pytest.mark.asyncio
async def test_analyze_profile_happy_path():
    """Caminho feliz: visão + síntese retornam um ScoutReport completo conforme o AC1."""
    with patch("app.agents.scout.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_text_response("Fotos de móveis planejados finalizados, madeira clara."),
                _mock_json_response(VALID_REPORT_JSON),
            ]
        )

        result = await analyze_profile(MEDIA_SAMPLE, BRAND_PROFILE)

    assert result is not None
    assert result["refined_niche"] == "móveis planejados sob medida"
    assert result["recurring_topics"] == ["cozinhas planejadas", "processo de marcenaria"]
    assert result["suggested_segment"] is None
    # 3 posts -> teto de confidence é 0.6 (faixa 3-5), mesmo o modelo reportando 0.9
    assert result["confidence"] == 0.6


@pytest.mark.asyncio
async def test_analyze_profile_empty_media_returns_none_without_calling_models():
    """Mídia vazia retorna None imediatamente, sem chamar nenhum modelo (AC5)."""
    with patch("app.agents.scout.anthropic.AsyncAnthropic") as mock_client_cls:
        result = await analyze_profile([], BRAND_PROFILE)

    assert result is None
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_profile_segment_divergence_passthrough():
    """suggested_segment válido (presente na lista fixa) passa direto (AC4)."""
    diverging_report = {**VALID_REPORT_JSON, "suggested_segment": "construção civil"}

    with patch("app.agents.scout.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_text_response("Descrição visual qualquer."),
                _mock_json_response(diverging_report),
            ]
        )

        result = await analyze_profile(MEDIA_SAMPLE, BRAND_PROFILE)

    assert result["suggested_segment"] == "construção civil"


@pytest.mark.asyncio
async def test_analyze_profile_model_failure_returns_none():
    """Falha na chamada de síntese (Sonnet) retorna None, nunca levanta exceção (AC7)."""
    with patch("app.agents.scout.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_text_response("Descrição visual qualquer."),
                Exception("timeout simulado na API Anthropic"),
            ]
        )

        result = await analyze_profile(MEDIA_SAMPLE, BRAND_PROFILE)

    assert result is None


# ─── Robustez adicional (decisões de design do pre-flight) ──────────────────

@pytest.mark.asyncio
async def test_analyze_profile_vision_failure_still_produces_report():
    """Falha isolada na análise visual não aborta tudo — síntese segue só com texto."""
    with patch("app.agents.scout.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                Exception("falha simulada na visão"),
                _mock_json_response(VALID_REPORT_JSON),
            ]
        )

        result = await analyze_profile(MEDIA_SAMPLE, BRAND_PROFILE)

    assert result is not None
    assert result["refined_niche"] == "móveis planejados sob medida"


@pytest.mark.asyncio
async def test_analyze_profile_hallucinated_segment_is_nulled():
    """Segmento fora da lista fixa é descartado defensivamente, nunca repassado (AC4)."""
    hallucinated_report = {**VALID_REPORT_JSON, "suggested_segment": "marcenaria premium"}

    with patch("app.agents.scout.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_text_response("Descrição visual qualquer."),
                _mock_json_response(hallucinated_report),
            ]
        )

        result = await analyze_profile(MEDIA_SAMPLE, BRAND_PROFILE)

    assert result["suggested_segment"] is None


@pytest.mark.asyncio
async def test_analyze_profile_confidence_ceiling_scales_with_post_count():
    """8 posts -> teto 1.0, então o valor reportado pelo modelo passa sem ser reduzido."""
    many_posts = [{**MEDIA_SAMPLE[0], "id": f"media-{i}"} for i in range(8)]

    with patch("app.agents.scout.anthropic.AsyncAnthropic") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.messages.create = AsyncMock(
            side_effect=[
                _mock_text_response("Descrição visual qualquer."),
                _mock_json_response(VALID_REPORT_JSON),
            ]
        )

        result = await analyze_profile(many_posts, BRAND_PROFILE)

    assert result["confidence"] == 0.9


# ─── Testes unitários dos helpers (decisões de design isoladas) ─────────────

def test_confidence_ceiling_thresholds():
    assert _confidence_ceiling(0) == 0.3
    assert _confidence_ceiling(2) == 0.3
    assert _confidence_ceiling(3) == 0.6
    assert _confidence_ceiling(5) == 0.6
    assert _confidence_ceiling(6) == 1.0
    assert _confidence_ceiling(12) == 1.0


def test_image_url_for_video_uses_thumbnail_never_media_url():
    """Vídeo: media_url é o arquivo de vídeo, inutilizável para visão — só thumbnail_url serve."""
    video_item = {"media_type": "VIDEO", "media_url": "https://cdn.example.com/v.mp4", "thumbnail_url": "https://cdn.example.com/thumb.jpg"}
    assert _image_url_for(video_item) == "https://cdn.example.com/thumb.jpg"

    video_without_thumb = {"media_type": "VIDEO", "media_url": "https://cdn.example.com/v.mp4", "thumbnail_url": None}
    assert _image_url_for(video_without_thumb) is None


def test_image_url_for_image_uses_media_url():
    image_item = {"media_type": "IMAGE", "media_url": "https://cdn.example.com/i.jpg", "thumbnail_url": None}
    assert _image_url_for(image_item) == "https://cdn.example.com/i.jpg"


def test_pick_visual_candidates_skips_carousel_without_url():
    """CAROUSEL_ALBUM sem media_url/thumbnail_url no nível superior é pulado, sem quebrar."""
    urls = _pick_visual_candidates(MEDIA_SAMPLE, sample_size=6)
    assert len(urls) == 2  # media-1 (IMAGE) e media-2 (VIDEO, via thumbnail_url) — media-3 (carousel) pulado
    assert "https://cdn.example.com/media-1.jpg" in urls
    assert "https://cdn.example.com/media-2-thumb.jpg" in urls


def test_pick_visual_candidates_respects_sample_size():
    many_posts = [{**MEDIA_SAMPLE[0], "id": f"media-{i}", "media_url": f"https://cdn.example.com/{i}.jpg"} for i in range(10)]
    urls = _pick_visual_candidates(many_posts, sample_size=6)
    assert len(urls) == 6


def test_build_captions_block_includes_carousel_caption_even_without_image():
    """Post sem imagem utilizável (carousel) ainda contribui com a legenda para o sinal textual."""
    block = _build_captions_block(MEDIA_SAMPLE)
    assert "Antes e depois de uma reforma de cozinha" in block  # legenda do media-3 (sem imagem)


def test_build_captions_block_empty_media_returns_placeholder():
    assert _build_captions_block([{"caption": None}, {"caption": "  "}]) == "(nenhuma legenda disponível)"


def test_fixed_segments_matches_epic_list():
    """Trava a lista de segmentos usada no epic — mudança aqui é uma decisão de produto, não refactor incidental."""
    assert FIXED_SEGMENTS == [
        "construção civil", "arquitetura", "saúde", "dentista",
        "advogado", "contador", "comércio", "outro",
    ]
