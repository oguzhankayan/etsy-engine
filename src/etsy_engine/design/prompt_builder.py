"""Prompt Builder (Agent 6). Deterministic GPT-Image-2 prompt assembly.

Pure-Python templating (no LLM call) — fast, free, reproducible. Combines the
bundle item's purpose with the product's shared design system so every page is
on-brand. Text is rendered by GPT-Image-2 directly (validated in production).
"""
from __future__ import annotations

import json

from ..models import BundleItem, DesignSystem

# Print-quality + IP-safety guidance shared by every printable. The IP-safety line
# is what lets us ride event trends (World Cup, Olympics) without infringing —
# generic, original artwork only, never official marks.
BASE_GUIDANCE = (
    "High-resolution printable design, 300 DPI quality, clean print-ready layout, "
    "centered composition, generous margins, no watermark, no extra UI. "
    "Render all text crisply and spelled exactly as specified. "
    "CRITICAL — EMPTY WRITE-IN FIELDS: every field the buyer fills by hand "
    "(amounts, names, dates, totals, blanks, table cells) must be COMPLETELY "
    "EMPTY. Never print example values ('$0.00', '0', sample names/dates), "
    "never print bracket placeholders ('[Name]', '[###]'). Blank lines and "
    "empty boxes only. "
    "CRITICAL — THE PAGE IS THE PRODUCT: this page is the usable printable "
    "artifact itself, NOT a poster, advertisement, infographic or size chart "
    "ABOUT the product. No marketing copy, no feature lists, no '3 sizes' "
    "callouts, no product-name banner headers unless the item spec explicitly "
    "asks for a title on the page. "
    "CRITICAL — PRINT SCALE: everything on the page must be usable at its "
    "printed size on US Letter/A4. ONE game board per page; cards 4-6 per "
    "page at minimum 2.5x3.5 inches each. Never render a miniature grid of "
    "many boards/cards on one sheet. "
    "Clean, uncluttered layout with generous white space and a clear typography "
    "hierarchy — let the page breathe; do NOT cram illustrations into every corner, "
    "header, and margin. BUT keep the design warm, friendly and full of personality: "
    "a few CHARMING, well-placed hand-drawn accents and a cohesive cheerful palette. "
    "Minimal in CLUTTER, never in character — playful, inviting and delightful, "
    "not sterile or corporate. "
    "Use ONLY original, generic artwork: do NOT depict or reference any real brand "
    "names, company logos, official event emblems or trophies, trademarks, "
    "sports-team crests, mascots, or copyrighted characters."
)


# Wall-art archetype: a finished decorative print to frame, NOT a printable form.
WALL_ART_GUIDANCE = (
    "High-resolution decorative WALL ART print, poster-quality, 300 DPI, print-ready, "
    "portrait orientation suitable for framing, full-bleed artful composition. "
    "This is a finished framable artwork — a bold focal design — NOT a worksheet, "
    "planner, tracker, checklist or form: NO blank lines, NO checkboxes, NO tables, "
    "NO empty fields. At most a tasteful title or typographic treatment integrated "
    "into the art. Striking, gallery-worthy, cohesive palette, gorgeous and giftable. "
    "Keep all text and key elements within a central safe area with comfortable "
    "margins from every edge, so the design can be cropped to multiple standard frame "
    "ratios (2:3, 3:4, 4:5, 11:14, ISO A) without cutting off any words or focal art. "
    "Use ONLY original, generic artwork: do NOT depict or reference any real brand "
    "names, company logos, official event emblems or trophies, trademarks, "
    "sports-team crests, mascots, or copyrighted characters. "
    "HONESTY: these are flat printables to be written on BY HAND. Do NOT render the "
    "words 'editable', 'customizable', 'fillable', 'template', 'templates', 'Canva', "
    "or 'personalize/personalized' anywhere on the page — they are false here. If a "
    "label is needed use accurate words only: 'Printable', 'Print at Home', "
    "'Write-In', 'Fill by Hand', 'Instant Download'."
)


# Coloring-book archetype: bold B&W line-art pages designed to be printed and coloured.
COLORING_BOOK_GUIDANCE = (
    "CRITICAL: This is a BLACK-AND-WHITE line-art coloring page. "
    "ONLY black outlines on pure white background — NO colour whatsoever, "
    "NO greyscale, NO shading, NO hatching, NO fills, NO coloured elements. "
    "Bold, thick black outlines — simple chunky shapes, no fine detail. "
    "Clear white space inside every shape for colouring. "
    "NO text or typography on the page (except possibly a tiny unobtrusive page number). "
    "Cute, cozy, relaxing composition — kawaii-inspired. "
    "Full-bleed portrait composition with comfortable margins. "
    "This is a finished printable coloring page, ready for the buyer to colour. "
    "Use ONLY original generic artwork — no copyrighted characters or brands."
)


# Cut-out / assembly artifacts (banners, garlands, bunting, envelopes, boxes):
# the model loves drawing an ADVERTISEMENT of the kit instead of the kit. This
# guidance forces the actual usable artifact (the #118 banner lesson).
CUTOUT_GUIDANCE = (
    "CRITICAL — REAL CUT-OUT ARTIFACT: this page contains the ACTUAL usable "
    "pieces at print scale, filling the page: e.g. large pennant triangles or "
    "letter cards (a few per page, each 3-5 inches), with clean dashed CUT "
    "lines and solid FOLD lines. NOT a poster or infographic about the banner: "
    "no size charts, no hanging diagrams, no instruction lists, no product "
    "title header, no marketing phrases. For envelope/box templates: a "
    "geometrically CORRECT dieline — symmetric flaps that would truly fold "
    "and align, glue tabs on the correct edges, dashed fold / solid cut "
    "convention. If the piece set needs multiple pages, this page shows only "
    "ITS OWN pieces, edge to edge."
)

_CUTOUT_TYPES = ("banner", "bunting", "garland", "pennant", "envelope", "box",
                 "wallet", "cut_out", "cutout", "tag", "topper")


def _is_cutout(item: BundleItem) -> bool:
    hay = f"{item.asset_type} {item.name}".lower()
    return any(t in hay for t in _CUTOUT_TYPES)


def build_prompt(item: BundleItem, ds: DesignSystem) -> str:
    palette = ", ".join(json.loads(ds.palette or "[]")) or "a cohesive color palette"
    if item.asset_type == "wall_art":
        parts = [
            f"\"{item.name}\" — original decorative wall art print.",
            f"Artwork: {item.spec}." if item.spec else "",
            f"Aesthetic: {ds.aesthetic}." if ds.aesthetic else "",
            f"Visual style: {ds.style_notes}." if ds.style_notes else "",
            f"Color palette: {palette}.",
            WALL_ART_GUIDANCE,
        ]
        return " ".join(p for p in parts if p)
    if item.asset_type in ("coloring_page", "coloring sheet", "colour"):
        parts = [
            f"A bold-and-easy coloring page titled \"{item.name}\".",
            f"Subject: {item.spec}." if item.spec else "",
            f"Aesthetic: {ds.aesthetic}." if ds.aesthetic else "",
            f"Color palette (for cover/preview only — the page itself is B&W line art): {palette}.",
            COLORING_BOOK_GUIDANCE,
        ]
        return " ".join(p for p in parts if p)
    parts = [
        f"A {item.asset_type.replace('_', ' ')} titled \"{item.name}\".",
        f"Purpose: {item.spec}." if item.spec else "",
        f"Aesthetic: {ds.aesthetic}." if ds.aesthetic else "",
        f"Visual style: {ds.style_notes}." if ds.style_notes else "",
        f"Icons/illustrations: {ds.icon_style}." if ds.icon_style else "",
        f"Typography feel: {ds.typography}." if ds.typography else "",
        f"Color palette: {palette}.",
        BASE_GUIDANCE,
    ]
    if _is_cutout(item):
        parts.append(CUTOUT_GUIDANCE)
    return " ".join(p for p in parts if p)
