"""Canva-editable product line (ADDITIVE — independent of the primary PDF pipeline).

v3 pipeline (validated 2026-07-05): the image model renders the WHOLE finished
design, then Canva Magic Layers (the owner's manual final touch) makes it editable.

  design    — aesthetics + MAGIC_LAYERS_RULES + brand constants (CONTACT_EMAIL)
  architect — LLM: niche -> content (title, subtitle, a few icon+label items)
  poster    — build the Magic-Layers-ready design image prompt + generate (-> Raywake)
  delivery  — the buyer's branded delivery PDF (how-to, review request, contact, link)
  copy      — honest 'editable Canva template' Etsy title/tags/description
  produce   — prepare(niche): plan -> image -> delivery PDF + listing (the automated half)

  render, art — RETIRED HTML-layout path (kept only for the back-compat shim + tests).

Owner workflow: engine builds the draft; owner runs Magic Layers, shares the template,
pastes the link back, and publishes. See docs/canva-line.md.
"""
from . import architect, art, copy, delivery, design, detect, poster, produce, render  # noqa: F401  (submodule re-exports)
from .copy import DELIVERY_INSTRUCTIONS, listing_copy
from .delivery import build_pdf
from .design import AESTHETICS, CONTACT_EMAIL, MAGIC_LAYERS_RULES, aesthetic, lint
from .poster import build_prompt
from .produce import prepare
from .render import LAYOUTS, render_pages

__all__ = [
           "AESTHETICS",
           "CONTACT_EMAIL",
           "DELIVERY_INSTRUCTIONS",
           "LAYOUTS",
           "MAGIC_LAYERS_RULES",
           "aesthetic",
           "architect",
           "art",
           "build_pdf",
           "build_prompt",
           "copy",
           "delivery",
           "design",
           "lint",
           "listing_copy",
           "poster",
           "prepare",
           "produce",
           "render",
           "render_pages",
]
