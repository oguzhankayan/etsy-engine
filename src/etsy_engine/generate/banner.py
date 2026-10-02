"""Deterministic letter-banner compositor.

Banners are the ONE decor form we produce mechanically, never as flat AI pages
(the #11 lesson). Method: generate a single themed BLANK pennant once (Raywake), then
stamp glyphs/words onto copies of it with a bundled serif at a fixed color — so
every flag in a set is byte-for-byte identical except its letter, spelling is
always correct, and each page is one usable print-and-cut pennant at A4/300dpi.

The architect emits a single component with asset_type "letter_banner" whose spec
carries a structured directive (see parse_spec); generator.py routes such items
here instead of the AI image path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import OUTPUT_DIR
from ..models import BundleItem, DesignSystem

ASSET_TYPE = "letter_banner"
FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Gelasio.ttf"

A4 = (2480, 3508)            # 300 dpi portrait
DEFAULT_COLOR = (54, 68, 40)  # forest green fallback
MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
          "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]

# Placement as fractions of the pennant image (robust to output size).
CX_F = 0.50          # horizontal center of the flag
GLYPH_CY_F = 0.36    # vertical center for a single big letter
GLYPH_FS_F = 0.34    # single-glyph font size as a fraction of image height (proven)
WORD_CY_F = 0.36
WORD_FS_START_F = 0.26  # starting word font size (shrinks to fit width)
WORD_MAXW_F = 0.72   # max word width as a fraction of image width


def is_banner(item) -> bool:
    return getattr(item, "asset_type", "") == ASSET_TYPE


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40] or "banner"


def page_dir(product_id: int, name: str) -> Path:
    """Where render_banner writes a banner's per-page JPEGs (used by delivery)."""
    return OUTPUT_DIR / str(product_id) / "banners" / slug(name)


def _font(px: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_PATH), px)
    try:
        f.set_variation_by_axes([700])   # bold weight on the variable font
    except Exception:
        pass
    return f


def _letter_color(ds: DesignSystem | None) -> tuple[int, int, int]:
    """Darkest palette color reads as ink on the cream pennant; else forest green."""
    try:
        pal = json.loads(ds.palette) if ds and ds.palette else []
        rgbs = []
        for h in pal:
            h = str(h).lstrip("#")
            if len(h) == 6:
                rgbs.append(tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)))
        if rgbs:
            return min(rgbs, key=sum)
    except Exception:
        pass
    return DEFAULT_COLOR


# --- themed blank pennant (one image call per product, cached) ---

def _pennant_prompt(ds: DesignSystem | None) -> str:
    motif = "small rustic seasonal motif"
    if ds:
        motif = f"a small motif matching this theme: {ds.aesthetic or ''} {ds.icon_style or ''}".strip()
    return (
        "A single blank swallowtail pennant banner flag hanging alone, aged cream "
        "ivory parchment paper with subtle vintage texture, thin hand-drawn border "
        "outline tracing the flag edge, deep V fishtail notch at the bottom, "
        f"{motif} painted small in the lower-center just above the notch, the entire "
        "upper two-thirds left completely blank and empty (no letter, no text), "
        "upright, isolated on a pure plain white background, no string, no words.")


def themed_pennant(ds: DesignSystem | None, product: dict, regen: bool = False) -> Path:
    """Return a cached themed blank pennant PNG for this product, generating it via
    Raywake on first use. Reused for every banner item in the product."""
    out = OUTPUT_DIR / str(product["id"]) / "_pennant.png"
    if out.exists() and not regen:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    from .image_client import get_image_client
    img = get_image_client().generate(_pennant_prompt(ds), size="1024x1536")
    out.write_bytes(img)
    return out


# --- page composition ---

def _fit_font(draw, text: str, max_w: int, start: int) -> ImageFont.FreeTypeFont:
    px = start
    while px > 60:
        f = _font(px)
        bb = draw.textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= max_w:
            return f
        px -= 20
    return _font(60)


def _stamp(pennant: Image.Image, text: str, color, cy_f: float, font) -> Image.Image:
    im = pennant.copy()
    d = ImageDraw.Draw(im)
    bb = d.textbbox((0, 0), text, font=font)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    x = int(im.width * CX_F) - w // 2 - bb[0]
    y = int(im.height * cy_f) - h // 2 - bb[1]
    d.text((x, y), text, font=font, fill=color)
    return im


def _to_a4(pennant: Image.Image) -> Image.Image:
    maxh = int(A4[1] * 0.86)
    scale = maxh / pennant.height
    pen = pennant.resize((int(pennant.width * scale), maxh), Image.LANCZOS)
    page = Image.new("RGB", A4, (255, 255, 255))
    page.paste(pen, ((A4[0] - pen.width) // 2, (A4[1] - pen.height) // 2))
    return page


def _glyph_page(pennant, ch, color):
    font = _font(int(pennant.height * GLYPH_FS_F))
    return _to_a4(_stamp(pennant, ch, color, GLYPH_CY_F, font))


def _word_page(pennant, word, color):
    d = ImageDraw.Draw(pennant)
    font = _fit_font(d, word, int(pennant.width * WORD_MAXW_F),
                     int(pennant.height * WORD_FS_START_F))
    return _to_a4(_stamp(pennant, word, color, WORD_CY_F, font))


def _blank_page(pennant):
    return _to_a4(pennant.copy())


# --- spec parsing ---

def parse_spec(spec: str) -> list[tuple[str, str]]:
    """Turn a letter_banner spec into an ordered list of (kind, text) pages.

    Accepts a JSON directive embedded anywhere in the spec:
      {"banner": {"kind": "alphabet", "numbers": true}}
      {"banner": {"kind": "word", "text": "WELCOME"}}
      {"banner": {"kind": "months"}} | {"kind":"words","words":[...]}
      {"banner": {"segments": [ {..}, {..} ]}}
      {"banner": {"kind": "blanks", "count": 3}}
    Falls back to keyword sniffing of free text (alphabet / months / a quoted WORD).
    """
    directive = _extract_json(spec)
    segments = []
    if directive:
        b = directive.get("banner", directive)
        segments = b.get("segments") or [b]
    if not segments:
        segments = _sniff(spec)

    pages: list[tuple[str, str]] = []
    for seg in segments:
        kind = (seg.get("kind") or "").lower()
        if kind == "alphabet":
            for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                pages.append(("glyph", ch))
            if seg.get("numbers"):
                for ch in "0123456789":
                    pages.append(("glyph", ch))
        elif kind in ("word", "letters"):
            for ch in (seg.get("text") or "").upper():
                pages.append(("blank", "") if ch == " " else ("glyph", ch))
        elif kind in ("months", "calendar"):
            for m in MONTHS:
                pages.append(("word", m))
        elif kind == "words":
            for w in seg.get("words") or []:
                pages.append(("word", str(w).upper()))
        elif kind == "blanks":
            for _ in range(int(seg.get("count") or 3)):
                pages.append(("blank", ""))
    return pages


def _extract_json(spec: str) -> dict | None:
    if not spec or "{" not in spec:
        return None
    depth, start = 0, None
    for i, c in enumerate(spec):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(spec[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


def _sniff(spec: str) -> list[dict]:
    s = (spec or "").lower()
    segs: list[dict] = []
    if "alphabet" in s or "a-z" in s or "a to z" in s:
        segs.append({"kind": "alphabet", "numbers": "number" in s or "0-9" in s})
    if "month" in s or "birthday board" in s:
        segs.append({"kind": "months"})
    m = re.search(r"['\"]([A-Za-z][A-Za-z ]{1,20})['\"]", spec or "")
    if m:
        segs.append({"kind": "word", "text": m.group(1)})
    if not segs:
        segs.append({"kind": "word", "text": "WELCOME"})
    return segs


# --- entry point used by the generator ---

def render_banner(item: BundleItem, ds: DesignSystem | None, product: dict) -> dict:
    """Render a letter_banner item to per-page JPEGs + a combined PDF.

    Returns {"pdf": Path, "pages": [Path], "count": int}. The PDF is the item's
    stored asset; per-page JPEGs live under output/<pid>/banners/<slug>/ for the zip.
    """
    color = _letter_color(ds)
    pennant = Image.open(themed_pennant(ds, product)).convert("RGB")
    pages_spec = parse_spec(item.spec) or [("word", "WELCOME")]

    sl = slug(item.name)
    pdir = page_dir(product["id"], item.name)
    pdir.mkdir(parents=True, exist_ok=True)

    page_paths: list[Path] = []
    imgs: list[Image.Image] = []
    for i, (kind, text) in enumerate(pages_spec, 1):
        if kind == "glyph":
            page = _glyph_page(pennant, text, color)
            label = text
        elif kind == "word":
            page = _word_page(pennant, text, color)
            label = text
        else:
            page = _blank_page(pennant)
            label = "blank"
        p = pdir / f"{i:02d}_{re.sub(r'[^A-Za-z0-9]+', '', label) or 'blank'}.jpg"
        page.save(p, "JPEG", quality=95)
        page_paths.append(p)
        imgs.append(page)

    pdf = OUTPUT_DIR / str(product["id"]) / f"{item.id}_{sl}.pdf"
    imgs[0].save(pdf, "PDF", resolution=300.0, save_all=True, append_images=imgs[1:])
    return {"pdf": pdf, "pages": page_paths, "count": len(imgs)}
