"""
SlideDesigner — gera imagens PNG de slides para carrossel autônomo.
Usa Pillow (PIL). Zero custo, zero dependência externa.
Layout: fundo na cor primária da marca, texto em branco.
"""
import io
import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Dimensões Instagram square
SLIDE_W = 1080
SLIDE_H = 1080
PADDING = 80

# Cores default (sobrescritas pelo brand_profile)
DEFAULT_BG_COLOR = (35, 84, 232)   # azul AutoPost
DEFAULT_TEXT_COLOR = (255, 255, 255)
ACCENT_COLOR = (255, 255, 255)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Converte hex (#RRGGBB ou RRGGBB) para tuple RGB."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return DEFAULT_BG_COLOR
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return DEFAULT_BG_COLOR


def _darken(color: tuple[int, int, int], factor: float = 0.7) -> tuple[int, int, int]:
    """Escurece uma cor pelo fator dado."""
    return tuple(max(0, int(c * factor)) for c in color)


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Retorna fonte. Tenta fontes do sistema, fallback para default."""
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",      # Linux (Railway)
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",                            # Windows (dev)
        "/System/Library/Fonts/Helvetica.ttc",                        # macOS
    ]
    for path in font_candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # Fallback absoluto — sem tipografia customizada
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Quebra texto em linhas respeitando max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_slide(
    headline: str,
    body: str | None,
    bg_color: tuple[int, int, int],
    slide_index: int,
    total_slides: int,
    company_name: str,
    tag: str | None = None,  # ex: "1/5", "INÍCIO", "FIM"
) -> bytes:
    """
    Renderiza um slide e retorna bytes PNG.
    """
    # Cria canvas
    img = Image.new("RGB", (SLIDE_W, SLIDE_H), bg_color)
    draw = ImageDraw.Draw(img)

    # Barra inferior levemente escurecida
    bar_h = 100
    dark = _darken(bg_color)
    draw.rectangle([(0, SLIDE_H - bar_h), (SLIDE_W, SLIDE_H)], fill=dark)

    # Nome da empresa na barra inferior (esquerda)
    font_small = _get_font(32)
    draw.text((PADDING, SLIDE_H - bar_h + 34), company_name, font=font_small, fill=ACCENT_COLOR)

    # Número do slide (direita)
    slide_label = tag or f"{slide_index}/{total_slides}"
    bbox = draw.textbbox((0, 0), slide_label, font=font_small)
    label_w = bbox[2] - bbox[0]
    draw.text((SLIDE_W - PADDING - label_w, SLIDE_H - bar_h + 34), slide_label, font=font_small, fill=ACCENT_COLOR)

    # Linha separadora acima da barra
    draw.rectangle(
        [(PADDING, SLIDE_H - bar_h - 2), (SLIDE_W - PADDING, SLIDE_H - bar_h)],
        fill=(255, 255, 255, 80),
    )

    # Área de conteúdo
    content_area_h = SLIDE_H - bar_h - PADDING
    max_text_w = SLIDE_W - (PADDING * 2)

    # Headline
    font_headline = _get_font(72)
    font_body = _get_font(44)

    headline_lines = _wrap_text(headline, font_headline, max_text_w, draw)

    # Calcula altura total do texto para centralizar verticalmente
    line_h_headline = 85
    line_h_body = 55
    total_text_h = len(headline_lines) * line_h_headline
    if body:
        body_lines = _wrap_text(body, font_body, max_text_w, draw)
        total_text_h += 40 + len(body_lines) * line_h_body  # 40px de margem
    else:
        body_lines = []

    y = (content_area_h - total_text_h) // 2 + PADDING // 2

    # Desenha headline
    for line in headline_lines:
        draw.text((PADDING, y), line, font=font_headline, fill=DEFAULT_TEXT_COLOR)
        y += line_h_headline

    # Desenha body
    if body_lines:
        y += 30  # margem entre headline e body
        for line in body_lines:
            draw.text((PADDING, y), line, font=font_body, fill=(220, 220, 220))
            y += line_h_body

    # Converte para PNG bytes
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


async def render_carousel_slides(
    structure: dict,
    brand_profile: dict,
) -> list[bytes]:
    """
    Renderiza todos os slides do carrossel e retorna lista de bytes PNG.

    Args:
        structure: saída de generate_slide_structure()
        brand_profile: perfil da marca (company_name, primary_color)

    Returns:
        Lista de bytes PNG, um por slide (título + conteúdo + CTA)
    """
    primary_hex = brand_profile.get("primary_color", "#2354E8")
    bg_color = _hex_to_rgb(primary_hex)
    company_name = brand_profile.get("company_name", "AutoPost")

    content_slides = structure.get("content_slides", [])
    total_slides = 1 + len(content_slides) + 1  # título + conteúdo + CTA

    slide_bytes: list[bytes] = []

    # 1. Slide de título
    title_card = structure["title_card"]
    title_png = _draw_slide(
        headline=title_card["headline"],
        body=title_card.get("subheadline"),
        bg_color=bg_color,
        slide_index=1,
        total_slides=total_slides,
        company_name=company_name,
        tag="INÍCIO",
    )
    slide_bytes.append(title_png)
    logger.info(f"[slide_designer] slide título gerado: {len(title_png)} bytes")

    # 2. Slides de conteúdo
    for i, slide in enumerate(content_slides, start=2):
        png = _draw_slide(
            headline=slide["headline"],
            body=slide.get("body"),
            bg_color=bg_color,
            slide_index=i,
            total_slides=total_slides,
            company_name=company_name,
            tag=f"{i - 1}/{len(content_slides)}",
        )
        slide_bytes.append(png)
        logger.info(f"[slide_designer] slide {i} gerado: {len(png)} bytes")

    # 3. CTA card
    cta_card = structure["cta_card"]
    cta_png = _draw_slide(
        headline=cta_card["headline"],
        body=cta_card.get("body"),
        bg_color=_darken(bg_color, 0.85),  # levemente mais escuro
        slide_index=total_slides,
        total_slides=total_slides,
        company_name=company_name,
        tag="FIM",
    )
    slide_bytes.append(cta_png)
    logger.info(f"[slide_designer] CTA gerado: {len(cta_png)} bytes total_slides={total_slides}")

    return slide_bytes
