"""Etsy listing attributes (per the official Search guide).

Attributes are category-specific structured fields (color, occasion, holiday,
style...). Each acts like a tag AND powers the filter sidebar — "the only way a
listing appears in filtered search is if it has that attribute." We set the
high-value ones for printables: Primary/Secondary color (from the design system)
and Occasion/Holiday/Style (from the product), choosing values that actually
exist in the taxonomy's fixed lists.
"""
from __future__ import annotations

import json

from ..llm import complete_json
from . import etsy_client as ec

# Properties worth setting for digital printables (by name, case-insensitive).
TARGET_PROPERTIES = {"primary color", "secondary color", "occasion", "holiday", "style"}

SYSTEM = """You set Etsy listing attributes. Given a product and the AVAILABLE
attribute options (fixed lists), choose the value(s) that ACCURATELY describe the
product. Rules:
- Only pick a value if it genuinely applies; otherwise omit that attribute.
- Colors: pick from the product's palette. Occasion/Holiday: only if the product
  is genuinely FOR that occasion (not just a possible gift).
- Use the EXACT value strings from the provided options.
Respond with JSON only: {"<attribute name>": ["Exact Value", ...], ...}"""


def fetch_properties(taxonomy_id: int) -> list[dict]:
    data = ec.app_request("GET", f"/seller-taxonomy/nodes/{taxonomy_id}/properties")
    return data.get("results", []) or []


def choose_and_set(listing_id: int, shop_id: str, product: dict,
                   design_system, taxonomy_id: int) -> int:
    """Pick applicable attribute values via Claude and PUT them. Returns count set."""
    props = [p for p in fetch_properties(taxonomy_id)
             if (p.get("name") or "").lower() in TARGET_PROPERTIES
             and p.get("possible_values")]
    if not props:
        return 0

    palette = json.loads(design_system.palette or "[]") if design_system else []
    options = {p["name"]: [v["name"] for v in p["possible_values"]] for p in props}
    user = json.dumps({
        "bundle_type": product["bundle_type"],
        "title_concept": product.get("title_concept", ""),
        "palette_hex": palette,
        "aesthetic": getattr(design_system, "aesthetic", "") if design_system else "",
        "available_attributes": options,
    }, ensure_ascii=False)

    try:
        chosen = complete_json(SYSTEM, user)
    except Exception as e:
        print(f"[attributes] selection failed: {e}")
        return 0

    set_count = 0
    for p in props:
        picks = chosen.get(p["name"]) or []
        if isinstance(picks, str):
            picks = [picks]
        name_to_id = {v["name"].lower(): v["value_id"] for v in p["possible_values"]}
        value_ids, values = [], []
        for pick in picks:
            vid = name_to_id.get(str(pick).strip().lower())
            if vid:
                value_ids.append(vid)
                values.append(str(pick).strip())
        if not value_ids:
            continue
        try:
            ec.request(
                "PUT",
                f"/shops/{shop_id}/listings/{listing_id}/properties/{p['property_id']}",
                json={"value_ids": value_ids, "values": values},
            )
            set_count += 1
            print(f"[attributes] {p['name']}: {', '.join(values)}")
        except Exception as e:
            print(f"[attributes] set {p['name']} failed: {e}")
    return set_count
