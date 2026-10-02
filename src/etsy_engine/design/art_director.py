"""Art Director (Agent 5). Defines one cohesive visual system per bundle.

Claude picks a palette, aesthetic direction, icon style, and typography so every
page in the bundle looks like part of the same product. This is what keeps an
8-piece kit visually consistent.

SHARED by both product lines: the PDF line uses `design_system_for()` (DesignSystem for the
PDF prompt builder); the Canva line uses `art_direction()` (an aesthetic-shaped, research-grounded
design system for `canva.poster`). One art-director brain, two output shapes.
"""
from __future__ import annotations

import json
import re

from ..llm import complete_json
from ..models import DesignSystem

SYSTEM = """You are an art director for Etsy printable/digital products. Given a
product bundle, define ONE cohesive visual system that every page will share.

Pick a style that fits the product's audience and is on-trend for Etsy buyers.
Aim for clean and uncluttered with generous white space and a limited palette —
but keep it WARM, PLAYFUL and full of character. Curated, charming decoration,
NOT illustrations crammed into every corner. Reduce clutter, not personality.
Respond with JSON only:
{"palette": ["#hex", "#hex", "#hex"],  // 3-4 colors, limited, cohesive, cheerful
 "aesthetic": "named direction, warm but uncluttered, e.g. 'playful minimal', 'cheerful boho', 'cozy modern'",
 "style_notes": "1-2 sentences; generous white space + uncluttered, yet warm and characterful",
 "icon_style": "a few charming hand-drawn accents used sparingly (not on every section)",
 "typography": "font feeling, e.g. 'friendly rounded sans with a playful handwritten accent'"}"""


def design_system_for(product: dict) -> DesignSystem:
    user = json.dumps({
        "bundle_type": product["bundle_type"],
        "title_concept": product["title_concept"],
    }, ensure_ascii=False)
    d = complete_json(SYSTEM, user)
    return DesignSystem(
        product_id=product["id"],
        palette=json.dumps(d.get("palette", [])),
        aesthetic=d.get("aesthetic", ""),
        style_notes=d.get("style_notes", ""),
        icon_style=d.get("icon_style", ""),
        typography=d.get("typography", ""),
    )


# --- Canva line: bespoke, research-grounded, full-design art direction --------------------------
# Same art-director brain, shaped for `canva.poster` (a whole finished image -> Magic Layers). The
# Canva line has 5 preset aesthetics as a floor; this replaces "snap to 1 of 5" with "invent the
# right look for THIS product + its niche". The caller injects its own `fallback` aesthetic (so this
# module needs no dependency on canva/), and it never raises.
_EM_DASH = re.compile(r"[—–]")

CANVA_SYSTEM = """You are the ART DIRECTOR for a premium Etsy shop selling editable Canva printable
templates. For ONE product, invent a BESPOKE design system that fits THIS product and, above all,
the design taste WINNING in its niche right now. Do NOT default to a generic "cream + serif +
florals" look unless the niche research truly calls for it. Make bold, specific, on-trend choices:
a kids party, a budget planner, a wedding sign, a gym log and a Halloween invite must look nothing
alike.

Hard craft constraints (the image goes through Canva Magic Layers, then to print):
- Background LIGHT, main text DARK ink on it, high contrast (>= 4.5:1). The accent colors are for
  LARGE display headings only, never for small body or label text. Flat illustrated/vector or
  clean-graphic look, NEVER photo-realistic. Large well-spaced text, distinct elements.
- No em dashes anywhere in your text.

Return ONLY one minified valid JSON object, no prose, no markdown fences. Inside string values use
plain words and single quotes only, NEVER double quotes; keep each value under 200 characters.
All fields required:
{"vibe":"short phrase naming the direction, e.g. bold retro arcade / calm sage minimalist / whimsical storybook",
 "palette":{"bg":"#hex light","ink":"#hex dark main text","accent":"#hex","accent2":"#hex"},
 "fonts":{"display":"a real display font/family feeling","body":"a real body font/family feeling"},
 "art_style":"concrete image-model directive for the illustration/graphic style + color mood",
 "type_prompt":"typography directive: serif vs bold sans vs rounded vs script; hierarchy",
 "frame_prompt":"decoration/framing directive: which motifs frame the page (or NONE-clean), how",
 "composition":"a strict LAYOUT directive every page obeys so the set looks like ONE professional product: the underlying grid/structure, ONE clear focal element, a strong 3-step size hierarchy (dominant title, medium headers, small body), generous CONSISTENT margins and alignment, and deliberate negative space (never crammed, never bare)"}"""

_NEUTRAL_DIRECTION = {
    "label": "clean modern", "palette": {"bg": "#FBFAF8", "ink": "#20242A", "ink_soft": "#5A6068",
                                          "accent": "#2F6E63", "accent2": "#20242A",
                                          "rule": "#E3E1DC", "gold": "#2F6E63"},
    "fonts": {"display": "a clean modern display", "body": "a clean sans body"},
    "art_style": "clean flat graphic, one calm accent color, lots of white space",
    "type_prompt": "a clear display title with a clean supporting typeface, strong size hierarchy",
    "frame_prompt": "minimal tasteful accents only, generous white space",
    "composition": "a calm single-column editorial grid: one dominant focal title, a clear "
                   "3-step size hierarchy, wide consistent margins, generous balanced negative space",
}


def _clean(s: str) -> str:
    return _EM_DASH.sub("-", str(s or "")).strip()


def _normalize_direction(raw: dict, fallback: dict) -> dict:
    """Coerce the LLM output into a valid aesthetic-shaped dict (poster never breaks)."""
    fp = fallback.get("palette", {})
    pin = raw.get("palette") or {}
    palette = {k: (pin.get(k) or fp.get(k) or _NEUTRAL_DIRECTION["palette"][k])
               for k in ("bg", "ink", "ink_soft", "accent", "accent2", "rule", "gold")}
    ff = fallback.get("fonts", {})
    fin = raw.get("fonts") or {}
    fonts = {"display": fin.get("display") or ff.get("display") or _NEUTRAL_DIRECTION["fonts"]["display"],
             "body": fin.get("body") or ff.get("body") or _NEUTRAL_DIRECTION["fonts"]["body"]}
    pick = lambda k: _clean(raw.get(k)) or fallback.get(k) or _NEUTRAL_DIRECTION[k]  # noqa: E731
    return {
        "label": _clean(raw.get("vibe")) or fallback.get("label", ""),
        "vibe": _clean(raw.get("vibe")) or fallback.get("label", ""),
        "palette": palette, "fonts": fonts,
        "art_style": pick("art_style"), "type_prompt": pick("type_prompt"),
        "frame_prompt": pick("frame_prompt"), "composition": pick("composition"),
        "bespoke": True,
    }


def art_direction(niche: str, product_kind: str = "", research: dict | None = None,
                  fallback: dict | None = None) -> dict:
    """Bespoke, aesthetic-shaped design system for one Canva product (grounded in `research`).

    `research` = a competitor design brief (see `canva.research`). `fallback` = an aesthetic-shaped
    dict the caller supplies for missing fields (e.g. `canva.design.aesthetic(name)`); if omitted a
    neutral default is used. Never raises: on any LLM/parse failure returns the fallback unchanged.
    """
    fb = fallback or _NEUTRAL_DIRECTION
    payload = {
        "niche": niche, "product": product_kind,
        "niche_design_research": {k: research.get(k) for k in
                                  ("palette", "motifs", "layout", "typography", "vibe", "brief")}
        if research else "none; infer a fitting, on-trend look for this niche",
    }
    user = json.dumps(payload, ensure_ascii=False)
    last = ""
    for _ in range(2):                       # a parse miss loses the bespoke look, so retry once
        try:
            raw = complete_json(CANVA_SYSTEM, user, max_tokens=900)
            if isinstance(raw, list):
                raw = raw[0] if raw else {}
            if isinstance(raw, dict) and raw.get("art_style"):
                return _normalize_direction(raw, fb)
            last = "empty/invalid shape"
        except Exception as e:  # noqa: BLE001 - design intelligence is best-effort
            last = str(e)[:120]
    print(f"[art-director] '{niche}' fell back ({last})")
    return {**fb, "bespoke": False}
