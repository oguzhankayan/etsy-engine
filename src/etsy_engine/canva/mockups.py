"""Etsy listing images for the Canva line.

There is ONE mockup engine, shared with the PDF line: mockups.generator.render_listing_set. This
module is just the Canva adapter over it (build_all) plus the resolution helpers produce.py uses.
The only Canva-specific difference is honesty: these ARE editable templates, so render_listing_set
is called with allow_editable=True (an 'Editable Canva Template' badge is welcome), whereas the flat
PDF line bans those words. No parallel scene/QC logic lives here anymore.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def build_all(design_urls: list[str], design_paths: list, title: str, out_dir: str | Path,
              aesthetic: str | None = None, product_id: int | None = None,
              style_brief: dict | None = None) -> list[Path]:
    """Canva listing images via the SHARED engine (mockups.generator.render_listing_set): the EXACT
    same scenes, quality and gated hero QC the PDF bundle line uses -- no parallel Canva mockup logic.
    The one honest difference: these ARE editable templates, so an 'Editable Canva Template' badge is
    allowed here (a flat PDF bans it). Returns the listing-image paths (hero, lifestyle, contents).

    When a product_id is given, each mockup is persisted to the DB `mockups` table exactly as the PDF
    line does (generator.generate_mockups), so metrics/reporting see Canva mockups too — one lifecycle."""
    from ..generate.generator import _store_path
    from ..models import Mockup
    from ..mockups.generator import render_listing_set
    from .. import db
    paths = [p for p in design_paths if Path(p).exists()]
    triples = render_listing_set(str(title).title(), list(design_urls), paths, out_dir,
                                 is_single=len(paths) <= 1, allow_editable=True,
                                 style_brief=style_brief)[:10]  # Etsy caps at 10
    images = []
    for kind, prompt, path in triples:
        _ensure_min_px(Path(path))                   # engine outputs 2048; keep the Etsy zoom floor
        images.append(Path(path))
        if product_id:
            db.upsert_mockup(Mockup(product_id=product_id, kind=kind,
                                    prompt=prompt, file_path=_store_path(Path(path))))
    return images


def _ensure_min_px(path: Path, min_short: int = 2000) -> None:
    """Upscale a listing image so its SHORT edge is >= min_short (Etsy's zoom threshold). Flat,
    illustrated template art upscales cleanly with Lanczos; fails soft."""
    try:
        im = Image.open(path).convert("RGB")
        short = min(im.size)
        if short < min_short:
            scale = min_short / short
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            im.save(path, "JPEG", quality=92)
    except Exception:  # noqa: BLE001
        pass


def _ensure_max_px(path: Path, max_short: int = 2400) -> None:
    """Downscale a page whose SHORT edge exceeds max_short. large renders (e.g. 4k ~3072x4608 at 2:3) but
    the real detail is gpt-image-2's ~1.5MP native upscaled, so pixels beyond a print-ready ceiling
    are interpolated bloat: ~2400px short (>Etsy's 2000 zoom threshold, and 300dpi past 5.5x8.5/letter)
    is plenty for a Canva template, and it keeps the delivered file small + fast to host/import."""
    try:
        im = Image.open(path).convert("RGB")
        short = min(im.size)
        if short > max_short:
            scale = max_short / short
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            im.save(path, "JPEG", quality=92)
    except Exception:  # noqa: BLE001
        pass
