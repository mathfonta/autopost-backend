"""
SlideDesigner v2 — gera imagens PNG de slides para carrossel autônomo.
Usa Pillow (PIL). Layout: gradiente diagonal, linha decorativa, tipografia em dois pesos.
"""
import io
import logging
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

SLIDE_W = 1080
SLIDE_H = 1080
PADDING = 72


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (35, 84, 232)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (35, 84, 232)


def _darken(color: tuple[int, int, int], factor: float = 0.65) -> tuple[int, int, int]:
    return tuple(max(0, int(c * factor)) for c in color)


def _lighten(color: tuple[int, int, int], factor: float = 1.35) -> tuple[int, int, int]:
    return tuple(min(255, int(c * factor)) for c in color)


def _lerp_color(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _draw_gradient(img: Image.Image, color_top: tuple, color_bottom: tuple) -> None:
    """Gradiente vertical suave de color_top para color_bottom."""
    draw = ImageDraw.Draw(img)
    for y in range(SLIDE_H):
        t = y / SLIDE_H
        # Curva cúbica para gradiente mais natural
        t_curved = t * t * (3 - 2 * t)
        color = _lerp_color(color_top, color_bottom, t_curved)
        draw.line([(0, y), (SLIDE_W, y)], fill=color)


def _get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    bold_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    regular_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    candidates = bold_candidates if bold else regular_candidates
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_decorative_accent(draw: ImageDraw.ImageDraw, color: tuple) -> None:
    """Retângulo decorativo no canto superior esquerdo — marca visual do slide."""
    accent_w, accent_h = 6, 80
    draw.rectangle([(PADDING, PADDING), (PADDING + accent_w, PADDING + accent_h)], fill=(255, 255, 255))
    draw.rectangle([(PADDING, PADDING + accent_h + 10), (PADDING + accent_w, PADDING + accent_h + 18)], fill=(255, 255, 255, 140))


def _draw_bottom_bar(draw: ImageDraw.ImageDraw, company_name: str, slide_label: str, bg_color: tuple) -> None:
    """Barra inferior semi-transparente com nome da empresa e número do slide."""
    bar_h = 90
    # Fundo escuro semi-transparente
    overlay = Image.new("RGBA", (SLIDE_W, bar_h), (*_darken(bg_color, 0.5), 210))
    # Não podemos compor aqui — ImageDraw opera em RGB; fazemos fill sólido
    dark = _darken(bg_color, 0.45)
    draw.rectangle([(0, SLIDE_H - bar_h), (SLIDE_W, SLIDE_H)], fill=dark)

    # Linha separadora
    draw.rectangle([(PADDING, SLIDE_H - bar_h), (SLIDE_W - PADDING, SLIDE_H - bar_h + 1)], fill=(255, 255, 255, 60))

    font_bar = _get_font(30)
    draw.text((PADDING + 14, SLIDE_H - bar_h + 28), company_name, font=font_bar, fill=(255, 255, 255))

    # Número do slide — direita
    bbox = draw.textbbox((0, 0), slide_label, font=font_bar)
    draw.text((SLIDE_W - PADDING - (bbox[2] - bbox[0]) - 14, SLIDE_H - bar_h + 28), slide_label, font=font_bar, fill=(255, 255, 255, 200))


def _draw_slide(
    headline: str,
    body: str | None,
    bg_color: tuple[int, int, int],
    slide_index: int,
    total_slides: int,
    company_name: str,
    tag: str | None = None,
    is_title: bool = False,
) -> bytes:
    img = Image.new("RGB", (SLIDE_W, SLIDE_H), bg_color)

    # Gradiente: cor primária → versão mais escura
    color_top    = _lighten(bg_color, 1.15)
    color_bottom = _darken(bg_color, 0.70)
    _draw_gradient(img, color_top, color_bottom)

    draw = ImageDraw.Draw(img)

    # Elemento decorativo
    _draw_decorative_accent(draw, bg_color)

    # Barra inferior
    slide_label = tag or f"{slide_index}/{total_slides}"
    _draw_bottom_bar(draw, company_name, slide_label, bg_color)

    # Área de texto
    bar_h    = 90
    max_text_w = SLIDE_W - (PADDING * 2) - 20

    font_headline = _get_font(76 if is_title else 68, bold=True)
    font_body     = _get_font(42, bold=False)

    headline_lines = _wrap_text(headline, font_headline, max_text_w, draw)
    body_lines     = _wrap_text(body, font_body, max_text_w, draw) if body else []

    lh_headline = 92 if is_title else 84
    lh_body     = 54
    gap         = 36

    total_text_h = len(headline_lines) * lh_headline
    if body_lines:
        total_text_h += gap + len(body_lines) * lh_body

    content_h = SLIDE_H - bar_h - PADDING
    y = max(PADDING + 110, (content_h - total_text_h) // 2 + PADDING // 2)

    # Headline (branco)
    for line in headline_lines:
        draw.text((PADDING + 14, y), line, font=font_headline, fill=(255, 255, 255))
        y += lh_headline

    # Body (branco 85% opacidade — tom levemente acinzentado)
    if body_lines:
        y += gap - 10
        for line in body_lines:
            draw.text((PADDING + 14, y), line, font=font_body, fill=(220, 224, 235))
            y += lh_body

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


async def render_carousel_slides(
    structure: dict,
    brand_profile: dict,
) -> list[bytes]:
    """
    Renderiza todos os slides do carrossel com design v2 (gradiente + tipografia aprimorada).
    """
    primary_hex  = brand_profile.get("primary_color", "#2354E8")
    bg_color     = _hex_to_rgb(primary_hex)
    company_name = brand_profile.get("company_name", "AutoPost")

    content_slides = structure.get("content_slides", [])
    total_slides   = 1 + len(content_slides) + 1

    slide_bytes: list[bytes] = []

    # Slide de título
    title_card = structure["title_card"]
    slide_bytes.append(_draw_slide(
        headline=title_card["headline"],
        body=title_card.get("subheadline"),
        bg_color=bg_color,
        slide_index=1,
        total_slides=total_slides,
        company_name=company_name,
        tag="INÍCIO",
        is_title=True,
    ))
    logger.info(f"[slide_designer_v2] título gerado")

    # Slides de conteúdo
    for i, slide in enumerate(content_slides, start=2):
        slide_bytes.append(_draw_slide(
            headline=slide["headline"],
            body=slide.get("body"),
            bg_color=bg_color,
            slide_index=i,
            total_slides=total_slides,
            company_name=company_name,
            tag=f"{i - 1}/{len(content_slides)}",
        ))
        logger.info(f"[slide_designer_v2] slide {i} gerado")

    # CTA
    cta_card = structure["cta_card"]
    slide_bytes.append(_draw_slide(
        headline=cta_card["headline"],
        body=cta_card.get("body"),
        bg_color=_darken(bg_color, 0.80),
        slide_index=total_slides,
        total_slides=total_slides,
        company_name=company_name,
        tag="FIM",
    ))
    logger.info(f"[slide_designer_v2] CTA gerado — total={total_slides} slides")

    return slide_bytes
