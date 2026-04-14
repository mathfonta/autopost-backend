"""
Testes do Agente Designer — não chama R2 real nem HTTP real.
Usa imagens PIL criadas em memória.
"""

from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.agents.designer import process_image

# ─── Helpers ────────────────────────────────────────────────────


def _img(w: int = 800, h: int = 600, color: tuple = (100, 150, 200)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


ANALYSIS_OBRA = {
    "content_type": "obra_realizada",
    "publish_clean": True,
    "description": "Acabamento de piso em porcelanato cinza 90x90.",
    "stage": "acabamento",
}

ANALYSIS_CARD = {
    "content_type": "dica",
    "publish_clean": False,
    "description": "5 dicas para melhorar o acabamento de paredes.",
    "stage": "",
}

ANALYSIS_ANTES_DEPOIS = {
    "content_type": "antes_depois",
    "publish_clean": False,
    "description": "Reforma completa de banheiro.",
    "stage": "",
}

ANALYSIS_PROMOCAO = {
    "content_type": "promocao",
    "publish_clean": False,
    "description": "Promoção de final de ano.",
    "stage": "",
}

BRAND = {
    "company_name": "Construtora Silva",
    "primary_color": "#1A3C6E",
    "logo_url": "",
}

FAKE_URL = "https://r2.example.com/processed/test-id/final.jpg"


# ─── Campos obrigatórios ────────────────────────────────────────


@pytest.mark.asyncio
async def test_clean_photo_returns_required_fields():
    """process_image deve retornar processed_photo_url, type, dimensions, file_size_kb."""
    with (
        patch("app.agents.designer._download_image", return_value=_img()),
        patch("app.agents.designer.upload_to_r2", new_callable=AsyncMock, return_value=FAKE_URL),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        result = await process_image("test-id", "https://r2.example.com/photo.jpg", ANALYSIS_OBRA, BRAND)

    assert "processed_photo_url" in result
    assert "type" in result
    assert "dimensions" in result
    assert "file_size_kb" in result


@pytest.mark.asyncio
async def test_clean_photo_type():
    """publish_clean=True + obra_realizada → type == clean_photo."""
    with (
        patch("app.agents.designer._download_image", return_value=_img()),
        patch("app.agents.designer.upload_to_r2", new_callable=AsyncMock, return_value=FAKE_URL),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        result = await process_image("id", "https://r2.example.com/p.jpg", ANALYSIS_OBRA, BRAND)

    assert result["type"] == "clean_photo"
    assert result["dimensions"] == "1080x1080"


@pytest.mark.asyncio
async def test_card_type_for_dica():
    """content_type=dica → type == card, não baixa foto original."""
    download_mock = AsyncMock()
    with (
        patch("app.agents.designer._download_image", download_mock),
        patch("app.agents.designer.upload_to_r2", new_callable=AsyncMock, return_value=FAKE_URL),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        result = await process_image("id", "https://r2.example.com/p.jpg", ANALYSIS_CARD, BRAND)
        download_mock.assert_not_called()

    assert result["type"] == "card"


@pytest.mark.asyncio
async def test_card_type_for_promocao():
    """content_type=promocao → type == card."""
    with (
        patch("app.agents.designer.upload_to_r2", new_callable=AsyncMock, return_value=FAKE_URL),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        result = await process_image("id", "https://r2.example.com/p.jpg", ANALYSIS_PROMOCAO, BRAND)

    assert result["type"] == "card"


@pytest.mark.asyncio
async def test_antes_depois_type():
    """content_type=antes_depois → type == antes_depois."""
    with (
        patch("app.agents.designer._download_image", return_value=_img()),
        patch("app.agents.designer.upload_to_r2", new_callable=AsyncMock, return_value=FAKE_URL),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        result = await process_image("id", "https://r2.example.com/p.jpg", ANALYSIS_ANTES_DEPOIS, BRAND)

    assert result["type"] == "antes_depois"


# ─── Upload R2 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_r2_key_format():
    """Chave do R2 deve seguir o padrão processed/{request_id}/final.jpg."""
    captured_keys = []

    async def fake_upload(key, data, content_type):
        captured_keys.append(key)
        return f"https://r2.example.com/{key}"

    with (
        patch("app.agents.designer._download_image", return_value=_img()),
        patch("app.agents.designer.upload_to_r2", side_effect=fake_upload),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        await process_image("abc-123", "https://r2.example.com/p.jpg", ANALYSIS_OBRA, BRAND)

    assert captured_keys == ["processed/abc-123/final.jpg"]


@pytest.mark.asyncio
async def test_processed_url_returned():
    """processed_photo_url deve ser a URL retornada pelo upload_to_r2."""
    async def fake_upload(key, data, content_type):
        return f"https://pub.r2.dev/{key}"

    with (
        patch("app.agents.designer._download_image", return_value=_img()),
        patch("app.agents.designer.upload_to_r2", side_effect=fake_upload),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        result = await process_image("xyz", "https://r2.example.com/p.jpg", ANALYSIS_OBRA, BRAND)

    assert result["processed_photo_url"] == "https://pub.r2.dev/processed/xyz/final.jpg"


# ─── Tamanho e robustez ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_output_below_8mb():
    """Imagem gerada deve ter menos de 8192 KB."""
    with (
        patch("app.agents.designer._download_image", return_value=_img(1200, 1200)),
        patch("app.agents.designer.upload_to_r2", new_callable=AsyncMock, return_value=FAKE_URL),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        result = await process_image("id", "https://r2.example.com/p.jpg", ANALYSIS_OBRA, BRAND)

    assert result["file_size_kb"] < 8192


@pytest.mark.asyncio
async def test_logo_failure_does_not_break_processing():
    """Falha ao baixar logo não deve interromper o processamento."""
    with (
        patch("app.agents.designer._download_image", return_value=_img()),
        patch("app.agents.designer.upload_to_r2", new_callable=AsyncMock, return_value=FAKE_URL),
        patch("app.agents.designer._get_logo", new_callable=AsyncMock, return_value=None),
    ):
        result = await process_image(
            "id",
            "https://r2.example.com/p.jpg",
            ANALYSIS_OBRA,
            {**BRAND, "logo_url": "https://invalid.example.com/logo.png"},
        )

    assert result["type"] == "clean_photo"
