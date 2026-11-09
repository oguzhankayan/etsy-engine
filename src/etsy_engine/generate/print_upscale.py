"""Optional print-resolution upscale before publishing.

Pages are generated at 1536x2048, which prints sharp only up to about 5x7 in at 300 DPI. Buyers print
on US Letter or A4, so before a listing is drafted `etsy-engine publish` offers to upscale each page 2x
(3072x4096) with Raywake's Bria Increase Resolution. It enlarges without redrawing, so the text on a
page stays exactly as it was. The delivery PDFs and PNGs are then built from the sharper pages.

It is opt-in and priced first: the CLI shows the number of pages and the quoted total, and only runs
on a yes (or `--upscale`). Each original page is kept next to it as `<name>.orig.jpg`, and a page that
is already print-sized is never upscaled again.
"""
from __future__ import annotations

import base64
import io
from decimal import Decimal
from pathlib import Path

MODEL = "bria/increase-resolution"
# A4 at 300 DPI is 2480 px wide and US Letter 2550; anything shorter prints soft at full page.
PRINT_SHORT_EDGE = 2400
BODY_BUDGET = 950_000  # Raywake caps a request body at about 1 MB


def _short_edge(path: Path) -> int:
    from PIL import Image
    with Image.open(path) as im:
        return min(im.size)


def pages_needing_upscale(product_id: int) -> list[Path]:
    """The product's printable pages that are below print size, in delivery order."""
    from ..publish.publisher import _asset_paths, _page_groups
    seen, pages = set(), []
    for path in [p for _, group in _page_groups(product_id) for p in group] + _asset_paths(product_id):
        path = Path(path)
        # Generated pages are JPEGs; a PNG or PDF asset is left as it is.
        if path in seen or path.suffix.lower() not in (".jpg", ".jpeg") or ".orig" in path.suffixes:
            continue
        seen.add(path)
        try:
            if _short_edge(path) < PRINT_SHORT_EDGE:
                pages.append(path)
        except OSError:
            continue
    return pages


def full_reference(path: Path, budget: int = BODY_BUDGET) -> str:
    """The page as a data URI at full size: quality drops before pixels do, so the upscale sees every detail."""
    from PIL import Image
    im = Image.open(path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    scale, quality = 1.0, 92
    while True:
        frame = im if scale == 1.0 else im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        frame.save(buf, format="JPEG", quality=quality, optimize=True)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        if len(uri) <= budget:
            return uri
        if quality > 70:
            quality -= 6
        else:
            scale *= 0.9


def _input(path: Path) -> dict:
    return {"image_url": full_reference(path), "desired_increase": 2, "output_type": "jpeg"}


def estimate_usd(client, pages: list[Path]) -> Decimal:
    """The quoted total: one quote for the first page times the page count (the price is per image)."""
    if not pages:
        return Decimal(0)
    quote = client.quote(MODEL, _input(pages[0]))
    return Decimal(int(quote["credits"])) / 100 * len(pages)


def upscale(client, pages: list[Path], say=print) -> int:
    """Upscale each page in place, keeping the original as <name>.orig.jpg. Returns pages upscaled."""
    from .generator import _to_jpeg
    done = 0
    for index, path in enumerate(pages, start=1):
        if _short_edge(path) >= PRINT_SHORT_EDGE:
            continue  # done on an earlier run
        say(f"  upscaling page {index}/{len(pages)}: {path.name}")
        data = _to_jpeg(client.run(MODEL, _input(path)), quality=92)
        original = path.with_name(path.stem + ".orig.jpg")
        if not original.exists():
            original.write_bytes(path.read_bytes())
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        done += 1
    return done
