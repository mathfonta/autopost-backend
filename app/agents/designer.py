"""
Agente Designer — processa imagens com Pillow e faz upload para Cloudflare R2.

Tipos de processamento:
  clean_photo  : resize 1080×1080 + logo discreto no canto inferior direito
  card         : cartão com fundo sólido na cor primária do cliente + texto + logo
  antes_depois : layout dividido 50/50 com labels "ANTES"/"DEPOIS" + logo
"""

import io
import logging

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.core.storage import upload_to_r2

logger = logging.getLogger(__name__)

TARGET_SIZE = (1080, 1080)
MAX_FILE_SIZE = 8 * 1024 * 1024       # 8 MB — limite Meta Graph API
LOGO_OPACITY = 153                     # 60 % de 255
LOGO_SIZE = (120, 120)
DEFAULT_PRIMARY_COLOR = "#1A3C6E"


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _download_image(url: str, r2_key: str = "") -> Image.Image:
    """Baixa imagem via R2 (boto3) se tiver r2_key, senão tenta HTTP."""
    if r2_key:
        from app.core.storage import download_from_r2
        data = await download_from_r2(r2_key)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


async def _get_logo(brand_profile: dict) -> Image.Image | None:
    """Tenta baixar logo do cliente. Retorna None se indisponível."""
    logo_url = brand_profile.get("logo_url", "")
    if not logo_url:
        return None
    try:
        return await _download_image(logo_url)
    except Exception as exc:
        logger.warning(f"[designer] logo indisponível: {exc}")
        return None


def _resize_square(img: Image.Image, size: int = 1080) -> Image.Image:
    """Recorta ao centro e redimensiona para quadrado."""
    w, h = img.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
    return img.resize((size, size), Image.LANCZOS)


def _add_logo(img: Image.Image, logo: Image.Image | None) -> Image.Image:
    """Cola logo no canto inferior direito com opacidade de 60 %."""
    if logo is None:
        return img
    logo_r = logo.convert("RGBA").resize(LOGO_SIZE, Image.LANCZOS)
    r, g, b, a = logo_r.split()
    a = a.point(lambda x: int(x * 0.6))
    logo_r = Image.merge("RGBA", (r, g, b, a))
    margin = 20
    pos = (img.width - LOGO_SIZE[0] - margin, img.height - LOGO_SIZE[1] - margin)
    img.paste(logo_r, pos, logo_r)
    return img


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _to_jpeg(img: Image.Image) -> bytes:
    """Converte para JPEG, comprimindo até ficar abaixo de 8 MB."""
    img_rgb = img.convert("RGB")
    quality = 92
    for _ in range(4):
        buf = io.BytesIO()
        img_rgb.save(buf, format="JPEG", quality=quality, optimize=True)
        if buf.tell() <= MAX_FILE_SIZE:
            break
        quality -= 10
    return buf.getvalue()


# ─── Processadores ──────────────────────────────────────────────────────────

def _process_clean_photo(img: Image.Image, logo: Image.Image | None) -> Image.Image:
    img = _resize_square(img)
    return _add_logo(img, logo)


def _load_font(size: int) -> ImageFont.ImageFont:
    """Carrega fonte com tamanho explícito (Pillow >= 10.1.0)."""
    return ImageFont.load_default(size=size)


def _process_card(description: str, brand_profile: dict, logo: Image.Image | None) -> Image.Image:
    """Card 1080×1080 com cor primária do cliente, texto e logo."""
    primary = brand_profile.get("primary_color", DEFAULT_PRIMARY_COLOR)
    try:
        bg = _hex_to_rgb(primary)
    except Exception:
        bg = _hex_to_rgb(DEFAULT_PRIMARY_COLOR)

    img = Image.new("RGBA", TARGET_SIZE, (*bg, 255))
    draw = ImageDraw.Draw(img)

    font_title = _load_font(52)
    font_body = _load_font(36)

    company = brand_profile.get("company_name", "")
    if company:
        draw.text((54, 80), company.upper(), fill=(255, 255, 255, 230), font=font_title)

    # Quebra o texto em linhas de ~38 caracteres
    words, lines, line = description.split(), [], ""
    for word in words:
        if len(line) + len(word) < 38:
            line += (" " + word if line else word)
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)

    y = 220
    for ln in lines[:12]:
        draw.text((54, y), ln, fill=(255, 255, 255, 200), font=font_body)
        y += 50

    return _add_logo(img, logo)


def _process_antes_depois(img: Image.Image, logo: Image.Image | None) -> Image.Image:
    """Layout dividido 50/50 com labels ANTES / DEPOIS."""
    img = _resize_square(img)
    draw = ImageDraw.Draw(img)
    mid = img.width // 2

    draw.line([(mid, 0), (mid, img.height)], fill=(255, 255, 255, 200), width=4)

    # Label ANTES
    draw.rectangle([(10, 10), (mid - 10, 70)], fill=(0, 0, 0, 160))
    draw.text((20, 20), "ANTES", fill=(255, 255, 255, 255))

    # Label DEPOIS
    draw.rectangle([(mid + 10, 10), (img.width - 10, 70)], fill=(0, 0, 0, 160))
    draw.text((mid + 20, 20), "DEPOIS", fill=(255, 255, 255, 255))

    return _add_logo(img, logo)


# ─── Função principal ────────────────────────────────────────────────────────

async def process_image(
    request_id: str,
    photo_url: str,
    analysis_result: dict,
    brand_profile: dict,
    photo_key: str = "",
) -> dict:
    """
    Processa a imagem e faz upload para Cloudflare R2.

    Args:
        request_id    : ID da ContentRequest (usado como chave no R2)
        photo_url     : URL da foto original no R2
        analysis_result: Saída do Agente Analista
        brand_profile  : Perfil de marca do cliente

    Returns:
        dict com: processed_photo_url, type, dimensions, file_size_kb, r2_key
    """
    content_type = analysis_result.get("content_type", "obra_realizada")
    publish_clean = analysis_result.get("publish_clean", True)
    description = analysis_result.get("description", "")

    logger.info(
        f"[designer] request_id={request_id} "
        f"content_type={content_type} publish_clean={publish_clean}"
    )

    logo = await _get_logo(brand_profile)

    if content_type == "antes_depois":
        design_type = "antes_depois"
        original = await _download_image(photo_url, photo_key)
        img = _process_antes_depois(original, logo)

    elif not publish_clean or content_type in ("dica", "promocao"):
        design_type = "card"
        img = _process_card(description, brand_profile, logo)

    else:
        design_type = "clean_photo"
        original = await _download_image(photo_url, photo_key)
        img = _process_clean_photo(original, logo)

    jpeg_bytes = _to_jpeg(img)
    file_size_kb = len(jpeg_bytes) // 1024

    key = f"processed/{request_id}/final.jpg"
    processed_url = await upload_to_r2(key, jpeg_bytes, "image/jpeg")

    logger.info(f"[designer] concluído type={design_type} size={file_size_kb}KB")

    return {
        "processed_photo_url": processed_url,
        "type": design_type,
        "dimensions": "1080x1080",
        "file_size_kb": file_size_kb,
        "r2_key": key,
    }
