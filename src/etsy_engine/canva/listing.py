"""Rich, theme-aware Etsy listing copy for the Canva-editable line.

Mirrors the PDF line's SEO writer (seo/writer.py) — keyword-researched copy plus
DETERMINISTIC winning tags (reusing seo.writer.build_tags) — but with two differences
that a generic "Editable Wedding Template | Canva" listing always misses:

1. HONESTY IS INVERTED. A Canva product IS an editable template, so the copy leans in:
   "editable Canva template", "personalize every detail", "free Canva account". The tag
   deny-list only drops formats/materials we don't ship (svg, cricut, physical goods),
   NOT canva/editable/customizable (those are honest and high-intent here).
2. It foregrounds the DESIGN THEME (the art director's vibe) and the ACTUAL pieces in
   the suite — the two things buyers scan for and the generic template never states.

One LLM call returns both the keyword set and the prose; tags are then assembled
deterministically from that set so the Etsy rules hold (<=20 chars, 13 distinct, real
market winners first).
"""
from __future__ import annotations

import json

from ..llm import complete_json
from ..seo.writer import AI_DISCLOSURE, TITLE_MAX, build_tags, ensure_keyword_in_title

# Formats/materials we do NOT offer on the Canva line. Unlike the PDF line, "canva",
# "editable", "customizable", "template", "printable" are HONEST here and stay.
CANVA_TAG_DENY = (
    "svg", "cut file", "cricut", "silhouette", "vinyl", "sublimation", "dxf", "eps",
    "png clipart", "clip art", "flat pdf", "pdf only", "non editable",
    "shirt", "tshirt", "t-shirt", " tee", "hoodie", "mug", "tumbler", "pillow",
    "blanket", "canvas print", "framed", "keychain", "magnet", "phone case",
)

SYSTEM = f"""You are an expert Etsy copywriter + keyword researcher for EDITABLE CANVA
TEMPLATES (2026 Etsy SEO). You get a real product: its niche, its DESIGN THEME, and the
exact pieces in the set. Write listing copy that sells THIS design, not a generic template.

Return BOTH a keyword set and the prose.

KEYWORDS (think like a buyer typing into Etsy; every phrase <=20 chars, lowercase, no
trademarks, diverse angles, no near-duplicate roots):
- Lean into the honest high-intent terms of this line: "editable", "canva template",
  "printable", "instant download" are GOOD here (this really is an editable Canva file).
- Capture the THEME/aesthetic as searchable style terms (e.g. an Amalfi/Tuscan vineyard
  wedding -> "italian wedding", "vineyard wedding", "tuscan wedding", "wine theme").
- Cover: product type, theme/style, occasion, who-it's-for, solution.

TITLE (Etsy official guidance):
- LEAD with the DESIGN THEME + what it IS ("Italian Vineyard Wedding Invitation Suite"),
  then a couple more phrases separated by | or :, and include "Editable Canva Template".
- ~70-110 chars, hard max {TITLE_MAX}. Do NOT repeat a word. Human-clear, keyword-rich.
- BANNED (this is the current generic default): a title that is just
  "Editable <Category> | Canva Template | Printable, Instant Download" with no theme.

DESCRIPTION (descriptions factor into ranking):
- First 1-2 sentences: evoke the THEME and weave a few top keywords naturally (don't
  copy the title, don't list keywords).
- Then "This set includes:" and BULLET the ACTUAL pieces you were given (name each).
- Then how it works: instant download with a link that opens the design in Canva;
  personalize every detail (names, dates, wording, colors, fonts); a FREE Canva account
  is all that's needed; edit on desktop or phone.
- Then printing: print at home or at a print shop; sized for US Letter and A4.
- Then "For personal use only."

HONESTY: it IS an editable Canva template — say so. Never claim SVG, Cricut/Silhouette
cut files, or any physical product.

Also write one concise alt_text per provided image kind, and a 3-4 pair FAQ (how to edit,
Canva account, printing/sizes, personal use).

Respond with JSON only:
{{"keywords": {{"primary_keyword": "...", "product_type_terms": ["..."], "long_tail": ["..."],
  "occasions": ["..."], "recipients": ["..."], "solutions": ["..."], "styles": ["..."],
  "formats": ["editable canva", "instant download", "printable"]}},
 "title": "...", "description": "...", "alt_texts": ["..."],
 "faq": "Q: ...\\nA: ...\\n\\nQ: ...\\nA: ..."}}"""


def _sanitize_title(raw: str, product_kind: str, niche: str = "") -> str:
    t = " ".join((raw or "").split()).strip()[:TITLE_MAX]
    if not t:
        # Non-generic fallback: LEAD with the niche/theme (the actual search term), never the
        # bare "Editable <kind> | Canva Template" default the prompt itself bans.
        base = " ".join(f"{niche} {product_kind}".split()).strip() or product_kind
        t = f"{base.title()} | Editable Canva Template | Printable Instant Download"[:TITLE_MAX]
    return t


def build(niche: str, product_kind: str, pieces: list[dict], theme: dict | None = None,
          market: dict | None = None, image_kinds: list[str] | None = None) -> dict:
    """Theme-aware Etsy listing (title/tags/description/alt/faq) for a Canva set.

    `pieces`: [{title, use}] per page (what's actually in the set). `theme`: the art
    direction (vibe/palette/motifs). `market`: the architect's _market signal (top_tags,
    titles). Falls back to `copy.listing_copy` upstream if the LLM call fails.
    """
    market = market or {}
    theme = theme or {}
    payload = {
        "niche": niche,
        "product_kind": product_kind,
        "design_theme": {k: theme.get(k) for k in ("vibe", "palette", "fonts", "motifs")
                         if theme.get(k)},
        "pieces_in_this_set": [{"shows": p.get("title"), "used_as": p.get("use")}
                               for p in pieces],
        "top_selling_titles": (market.get("titles") or [])[:8],
        "image_kinds_needing_alt_text": image_kinds or ["hero", "lifestyle", "contents"],
    }
    r = complete_json(SYSTEM, json.dumps(payload, ensure_ascii=False))
    if isinstance(r, list):
        r = next((x for x in r if isinstance(x, dict)), {})
    if not isinstance(r, dict) or not r.get("title"):
        raise ValueError("canva listing: empty LLM copy")

    kw = r.get("keywords") if isinstance(r.get("keywords"), dict) else {}
    # niche + theme seeded as real winners alongside the market's proven tags
    seed = [niche, " ".join(str(niche).split()[:2])] + (theme.get("style_terms") or [])
    tags = build_tags(kw, real_tags=(market.get("top_tags") or []) + seed,
                      deny=CANVA_TAG_DENY)

    desc = (r.get("description") or "").rstrip()
    if r.get("faq"):
        desc += "\n\n— FAQ —\n" + str(r["faq"]).strip()
    desc += AI_DISCLOSURE
    # Guarantee the primary search phrase (or, failing that, the niche) is in the title.
    title = _sanitize_title(r.get("title"), product_kind, niche)
    title = ensure_keyword_in_title(title, kw.get("primary_keyword") or niche)
    return {
        "title": title,
        "tags": tags,
        "description": desc,
        "alt_texts": r.get("alt_texts", []),
    }
