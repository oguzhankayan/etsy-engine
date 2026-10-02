"""Delivery PDF for Canva editable templates.

The buyer's Etsy digital file: a branded one-pager carrying the template link, how to
use it, a thank-you, a review request, and support contact. Built with Pillow at
A4/300dpi (the same toolchain as the print pipeline, no new dependency). The link is a
parameter because it only exists after the owner runs Magic Layers and shares the
template, so this PDF is (re)built with the real link at publish time.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import OUTPUT_DIR
from . import design as D

FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Gelasio.ttf"
A4 = (2480, 3508)                       # 300 dpi portrait
MARGIN = 300
LINK_PLACEHOLDER = "(paste your Canva template link here)"

STEPS = [
    "Click the template link below, or paste it into your browser.",
    'Choose "Use template" to open it in your own free Canva account.',
    "Edit the text, colors and photos to make it yours.",
    "Download as PDF or PNG, then print at home or share.",
]


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), px)


def _wrap(draw, text, font, max_w):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _block(draw, y, text, px, fill, max_w, center=True, gap=1.35):
    """Draw wrapped, centered text; return the y below it. (Tracked caps: pass
    the text pre-spaced, e.g. ' '.join('LABEL').)"""
    font = _font(px)
    for line in _wrap(draw, text, font, max_w):
        w = draw.textlength(line, font=font)
        x = (A4[0] - w) / 2 if center else MARGIN
        draw.text((x, y), line, font=font, fill=fill)
        y += int(px * gap)
    return y


def _rule(draw, y, color, w=360):
    x0 = (A4[0] - w) / 2
    draw.line([(x0, y), (x0 + w, y)], fill=color, width=4)
    return y + 40


def build_pdf(product_title: str, link: str | None = None, out_dir: str | Path | None = None,
              aesthetic: str | None = None) -> str:
    """Build the delivery PDF. Pass `link` once Magic Layers + share produced it."""
    aes = D.aesthetic(aesthetic)
    pal = aes["palette"]
    bg, ink, soft, accent, gold = (_rgb(pal["bg"]), _rgb(pal["ink"]),
                                   _rgb(pal["ink_soft"]), _rgb(pal["accent"]), _rgb(pal["gold"]))
    max_w = A4[0] - 2 * MARGIN

    img = Image.new("RGB", A4, bg)
    d = ImageDraw.Draw(img)

    y = 420
    y = _block(d, y, D.BRAND_NAME, 50, gold, max_w)
    y += 70
    y = _block(d, y, "Thank you for your order", 150, ink, max_w)
    y += 30
    y = _block(d, y, "Your editable Canva template is ready.", 58, soft, max_w)
    y += 20
    if product_title:
        y = _block(d, y, product_title, 62, accent, max_w)
    y += 50
    y = _rule(d, y, gold)
    y += 40

    y = _block(d, y, "How to use your template", 58, accent, max_w)
    y += 50
    step_font = _font(52)
    for i, step in enumerate(STEPS, 1):
        num = f"{i}."
        d.text((MARGIN, y), num, font=step_font, fill=gold)
        for line in _wrap(d, step, step_font, max_w - 90):
            d.text((MARGIN + 90, y), line, font=step_font, fill=ink)
            y += int(52 * 1.3)
        y += 24
    y += 40
    y = _rule(d, y, gold)
    y += 40

    y = _block(d, y, "Your template link", 58, accent, max_w)
    y += 44
    y = _block(d, y, link or LINK_PLACEHOLDER, 52, ink if link else soft, max_w, gap=1.4)
    y += 70

    y = _block(d, y, "Made by a small studio. If this made your day a little easier, "
               "a quick review truly helps us keep creating.", 54, ink, max_w)
    y += 60
    y = _block(d, y, "Questions or a tweak you need? We are happy to help:", 52, soft, max_w)
    y += 8
    y = _block(d, y, D.CONTACT_EMAIL or "Message us through Etsy.", 60, accent, max_w)

    out = Path(out_dir or (OUTPUT_DIR / "canva"))
    out.mkdir(parents=True, exist_ok=True)
    pdf_path = out / "delivery.pdf"
    img.save(pdf_path, "PDF", resolution=300.0)
    img.save(out / "delivery.png")            # sibling preview (QC + listing thumbnail)
    return str(pdf_path)
