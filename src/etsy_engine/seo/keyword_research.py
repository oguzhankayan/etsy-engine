"""Keyword research (Agent 10a). Claude as an Etsy keyword researcher.

Produces a structured, intent-segmented keyword set the listing writer assembles
from. Encodes the 2026 Etsy SEO playbook (see docs/etsy-seo.md): long-tail,
buyer-intent, semantic, gifting/occasion angles.
"""
from __future__ import annotations

import json

from .. import db
from ..llm import complete_json

SYSTEM = """You are a senior Etsy SEO keyword researcher specializing in digital
printables. Think like a buyer typing into Etsy search. Apply Etsy's official tag
guidance:
- favor LONG-TAIL, multi-word phrases over broad single words (they convert better)
- DIVERSIFY across Etsy's tag types so the 13 tags cover different angles, not
  variations of one root: descriptive, materials/techniques, who-it's-for,
  shopping-occasion, solution-oriented, style/aesthetic, size/format.
- do NOT produce near-duplicate roots (e.g. "octopus art print" AND "octopus
  print" — pick one and use the freed slot for a different angle).
- ignore singular/plural (Etsy matches root words) — don't spend two phrases on it.
- natural language a real shopper uses; no keyword stuffing, no trademarks.
- the product is a FLAT printable (print & write by hand), NOT editable/Canva —
  never include "editable", "customizable", "fillable", or "canva" tags.
- tag-ready phrases MUST be <= 20 characters and lowercase.

Given a product, return JSON only:
{
  "primary_keyword": "the single best 2-4 word phrase buyers search (<=20 chars if possible)",
  "product_type_terms": ["core product synonyms (descriptive)"],
  "long_tail": ["7-13 multi-word buyer phrases, each <=20 chars, DIVERSE angles"],
  "occasions": ["back to school", "..."],          // shopping occasions, <=20 chars
  "recipients": ["for teachers", "for moms", ...], // who it's for, <=20 chars
  "solutions": ["stay organized", "..."],          // problem it solves, <=20 chars
  "styles": ["boho", "minimalist", ...],           // aesthetic, <=20 chars
  "formats": ["instant download", "pdf printable", "a4 letter"],  // size/format
  "title_keywords": ["the 2-3 clearest phrases describing what it IS, for the title"]
}
All tag-style arrays MUST contain phrases <= 20 chars, lowercase, no duplicates,
no trademarks.
If "real_buyer_phrases" is provided (mined from actual buyer reviews in this
niche), prefer those words and their close variants in long_tail / solutions —
they are the language proven buyers actually use."""


def research(product: dict) -> dict:
    items = [b.name for b in db.bundle_items_for(product["id"])]
    payload = {
        "bundle_type": product["bundle_type"],
        "title_concept": product["title_concept"],
        "included_items": items,
    }
    # Buyer voice from review mining (cached at architect time): the words real
    # buyers use are the strongest long-tail candidates.
    try:
        from ..scoring.reviews import niche_review_insights
        term = (db.provenance(product["id"]) or {}).get("term")
        insights = niche_review_insights(term) if term else None
        if insights and insights.get("buyer_words"):
            payload["real_buyer_phrases"] = insights["buyer_words"]
    except Exception as e:
        print(f"[seo] buyer phrases skipped: {e}")
    return _as_dict(complete_json(SYSTEM, json.dumps(payload, ensure_ascii=False)))


def _as_dict(result) -> dict:
    """Normalize the LLM's JSON to the expected dict. Some models wrap the object
    in a single-element list (`[{...}]`); tolerate that instead of crashing."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                return item
    return {}
