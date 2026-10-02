"""Honest Etsy copy + the buyer-facing delivery text for Canva-editable products.

"Editable"/"Canva" are truthful here because a real, working template link ships
(the RULES §H5 gate). This is generated in-package and NEVER routed through the
shared seo/writer.py, so the primary PDF line's editable/Canva bans stay in force.
"""
from __future__ import annotations

import re

from .design import CONTACT_EMAIL

# Rendered onto the delivered PDF alongside the Canva Template link.
DELIVERY_INSTRUCTIONS = (
    "Your editable Canva template\n\n"
    "1. Open the template link below on a computer or phone.\n"
    "2. Sign in to Canva (a free account is fine) and click 'Use template' to get\n"
    "   your own private copy to edit.\n"
    "3. Click any text to change it, then download as PDF or PNG (high resolution).\n"
    "4. Print at home or at a local print shop. To fit US Letter or A4, use Canva's\n"
    "   Resize, or choose 'Fit to page' when printing.\n\n"
    "Template link:\n{link}\n\n"
    "For personal use only. Colors, fonts, and layout are fully editable in Canva.\n\n"
    "Thank you so much for your order. If it made your day easier, a quick review\n"
    "truly helps our small studio."
    + (f" Questions or a tweak you need? {CONTACT_EMAIL}" if CONTACT_EMAIL else
       " Questions or a tweak you need? Message us through Etsy.")
)


ETSY_TAG_MAXLEN = 20                          # Etsy rejects any tag longer than 20 chars


def _etsy_tags(candidates: list[str]) -> list[str]:
    """Enforce Etsy's tag rules: <=20 chars each, non-empty, de-duped (case-insensitive), max 13.

    Order is preserved, so put the highest-value tags (niche-specific) first.
    """
    out: list[str] = []
    seen: set[str] = set()
    for t in candidates:
        t = " ".join((t or "").split())       # normalize whitespace
        key = t.lower()
        if t and len(t) <= ETSY_TAG_MAXLEN and key not in seen:
            out.append(t)
            seen.add(key)
        if len(out) == 13:
            break
    return out


def listing_copy(product_kind: str = "Welcome Template", niche: str = "") -> dict:
    """Honest title/tags/description for a product that ships a REAL editable Canva template."""
    kind = (product_kind or "Welcome Template").strip()
    niche = (niche or "").strip()
    # The architect sometimes already puts "editable" in product_kind; strip it so we don't get
    # "Editable Editable ..." in the title.
    kind = re.sub(r"^editable\s+", "", kind, flags=re.IGNORECASE).strip() or kind
    lead = f"Editable {kind}"
    title = f"{lead} | Canva Template | Printable, Instant Download"
    if len(title) > 140:                      # Etsy title cap; never dump the raw niche
        title = title[:140].rsplit(" ", 1)[0]
    # Niche-specific tags first (best SEO), then evergreen ones. Every phrase is <=20 chars;
    # `_etsy_tags` drops anything longer (e.g. a long niche) and de-dupes, so tags stay valid.
    niche_tags = [niche, " ".join(niche.split()[:2])] if niche else []
    tags = _etsy_tags(niche_tags + [
        "canva template", "editable template", "editable printable",
        "printable template", "canva printable", "instant download",
        "digital download", "editable sign", "custom template",
        "diy printable", "print at home", "personalized gift", "canva design",
    ])
    desc = (
        "An EDITABLE Canva template (not a flat PDF). Your instant download includes a "
        "link that opens the design in Canva, where you personalize every detail and change "
        "the text, then download and print at home or at a print shop. A free Canva account "
        "is all you need; edit on desktop or phone. For personal use only."
    )
    return {"title": title, "tags": tags, "description": desc}
