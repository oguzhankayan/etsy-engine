"""Creative Director (Agent 5.5). The holistic craft gate the Canva pipeline lacked.

`qc.assess_text` only checks spelling/legibility. The creative director does a VISION review of the
rendered page for the things the owner flagged as weak: COMPOSITION (professional layout, one clear
focal point, hierarchy, balance, consistent margins), DESIGN-SYSTEM ADHERENCE (does the page use the
shared palette + typographic feel, so it reads as the SAME product family as its sibling pages), and
overall boutique CRAFT. Holding every page to ONE shared system is what keeps a multi-page set
CONSISTENT. Weak pages are flagged for one targeted regeneration. Fails soft (skipped/neutral) so a
missing key or a vision hiccup never breaks generation.
"""
from __future__ import annotations

from ..config import settings
from ..generate.qc import _prep_for_qc
from ..llm import vision_json

PASS = 0.6   # lenient: vision is noisy and a regen costs credits, so only genuinely weak pages regen

SYSTEM = """You are the CREATIVE DIRECTOR doing the final craft review of ONE page of a multi-page
editable Canva template before it ships to a premium boutique Etsy shop. You are told the shared
DESIGN SYSTEM every page must obey (palette, typography, composition, vibe) and the product. Judge
CRAFT and CONSISTENCY only, NOT spelling (that is checked elsewhere). Be a demanding art director.
Respond with JSON only:
{"composition": 0.0-1.0,      // professional layout: ONE clear focal point, strong size hierarchy,
       // balanced, aligned, generous CONSISTENT margins. Low if crammed, lopsided, chaotic, or bare.
 "system_adherence": 0.0-1.0, // uses the stated palette + typographic feel, so it reads as the SAME
       // product family as its sibling pages (this is what keeps the multi-page set consistent).
 "craft": 0.0-1.0,            // premium boutique quality; low if it looks amateur, generic, cluttered, or AI-sloppy.
 "score": 0.0-1.0,           // overall craft. composition and system_adherence are HARD: if either < 0.5, cap overall at 0.4.
 "fix": "the single highest-impact change to make on a regenerate, or 'ship'"}"""


def assess_page(image_bytes: bytes, direction: dict | None = None, spine: str = "",
                kind: str = "") -> dict:
    """Craft + consistency review of one rendered page. Returns {status, score, fix, ...}; never raises."""
    if not settings.anthropic_api_key:
        return {"status": "skipped", "score": 0.7, "fix": "no key"}
    d = direction or {}
    pal = d.get("palette") or {}
    fonts = d.get("fonts") or {}
    system_desc = (
        "DESIGN SYSTEM every page of this set shares — "
        f"vibe: {d.get('vibe') or d.get('label') or 'n/a'}; "
        f"palette: bg {pal.get('bg')}, ink {pal.get('ink')}, accent {pal.get('accent')}; "
        f"typography: {d.get('type_prompt') or fonts or 'n/a'}; "
        f"composition: {d.get('composition') or 'clean editorial grid, one focal point, wide margins'}. "
        f"Product: {kind or 'editable template'}." + (f" Shared spine: {spine}" if spine else "")
    )
    qc_bytes, qc_media = _prep_for_qc(image_bytes)
    try:
        r = vision_json(SYSTEM, system_desc, qc_bytes, media_type=qc_media)
    except Exception as e:  # noqa: BLE001 — creative direction is best-effort
        return {"status": "skipped", "score": 0.7, "fix": f"CD error: {e}"}
    score = float(r.get("score", 0.0))
    comp = float(r.get("composition", 1.0))
    adh = float(r.get("system_adherence", 1.0))
    failed = score < PASS or comp < 0.5 or adh < 0.5
    return {"status": "failed" if failed else "passed", "score": score,
            "composition": comp, "system_adherence": adh, "fix": r.get("fix", "")}
