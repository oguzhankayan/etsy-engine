"""Backward-compat shim. The Canva-editable line now lives in `etsy_engine.canva`
(design system + render + architect + art + produce + copy). This keeps the
original one-page "welcome" preset and the honest copy importable; new work should
use `etsy_engine.canva` (general, multi-page, any product type).

ADDITIVE: nothing here touches the primary print-at-home PDF pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..canva import art as _art, design as _design, render as _render
from ..canva.copy import DELIVERY_INSTRUCTIONS, listing_copy  # re-export

PAGE_CREAM = _design.AESTHETICS["botanical"]["palette"]["bg"]  # #FEF8EB
ART_PROMPT = _art.art_prompt(_design.aesthetic("botanical"))
ART_SIZE = _art.ART_SIZE

__all__ = [
    "ART_PROMPT",
    "DELIVERY_INSTRUCTIONS",
    "PAGE_CREAM",
    "CanvaSpec",
    "InfoSection",
    "build_html",
    "listing_copy",
    "prepare",
]


@dataclass
class InfoSection:
    label: str
    lines: list[str]


@dataclass
class CanvaSpec:
    """The editable fields of the one-page 'welcome' preset (a convenience default)."""
    title: str = "Welcome"
    note: list[str] = field(default_factory=lambda: [
        "We're so glad you're here.", "Settle in and make yourself at home."])
    section_header: str = "YOUR STAY"
    sections: list[InfoSection] = field(default_factory=lambda: [
        InfoSection("WI-FI", ["Network: YourNetwork", "Password: YourPass123"]),
        InfoSection("ARRIVAL & DEPARTURE", ["Check-in: from 3 PM", "Check-out: by 11 AM"]),
        InfoSection("HOUSE NOTES", ["No smoking indoors. Shoes off.", "Quiet hours after 10 PM."]),
        InfoSection("LOCAL FAVORITES", ["Coffee: The Corner Roastery", "Dinner: Olive & Vine"]),
    ])
    footer_title: str = "Enjoy your stay"
    footer_lines: list[str] = field(default_factory=lambda: [
        "Anything you need? Reach your host at +1 (555) 123-4567", "or hello@yourstay.com"])


def build_html(spec: CanvaSpec, art_url: str) -> str:
    """The welcome preset -> one crafted, editable page (delegates to the render core)."""
    content = {
        "title": spec.title, "note": spec.note, "section_header": spec.section_header,
        "sections": [{"label": s.label, "lines": s.lines} for s in spec.sections],
        "footer_title": spec.footer_title, "footer_lines": spec.footer_lines,
    }
    return _render.render_pages([{"layout": "welcome", "content": content}], "botanical", art_url)


def prepare(spec: CanvaSpec | None = None, out_dir: Path | None = None,
            art_url: str | None = None) -> dict:
    """Welcome-preset prepare: clean-interior art (Raywake) + hosted URL + HTML.
    For any-trend production use `etsy_engine.canva.produce.prepare(term)` instead."""
    from ..config import OUTPUT_DIR
    spec = spec or CanvaSpec()
    out = Path(out_dir or (OUTPUT_DIR / "canva"))
    out.mkdir(parents=True, exist_ok=True)
    art_path = out / "arch_art.png"
    if art_url is None:
        from .image_client import get_image_client
        from . import hosting
        img = get_image_client().generate(ART_PROMPT, size=ART_SIZE)
        art_path.write_bytes(img)
        art_url = hosting.public_url(str(art_path))
        if not art_url:
            raise RuntimeError("no public art URL — Canva import needs an HTTPS link")
    html_path = out / "template.html"
    html_path.write_text(build_html(spec, art_url), encoding="utf-8")
    return {"art_path": str(art_path), "art_url": art_url, "html_path": str(html_path)}
