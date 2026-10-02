"""Product report — the decision provenance behind each product.

Writes output/<product_id>/PRODUCT_REPORT.md so the operator can audit later:
which trend, what the signals were, what we looked at, and why we decided to make
this product. Read it back when iterating to improve the product.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import db
from .config import OUTPUT_DIR
from .models import now


def _fmt_tier(t) -> str:
    return {1: "Tier 1 Viral", 2: "Tier 2 Seasonal", 3: "Tier 3 Evergreen"}.get(t, str(t))


def write_product_report(product_id: int, refetch_competitors: bool = True) -> Path | None:
    p = db.provenance(product_id)
    if not p:
        print(f"[report] product {product_id} not found")
        return None

    items = db.bundle_items_for(product_id)
    ds = db.get_design_system(product_id)
    assets = db.assets_for_product(product_id)
    listing = db.get_listing(product_id)
    kw = db.get_keyword_set(product_id) or {}
    etsy = db.get_etsy_listing(product_id)
    payload = {}
    try:
        payload = json.loads(p.get("raw_payload") or "{}")
    except (ValueError, TypeError):
        pass

    # Current top competitors for the keyword (signal that informed the bundle).
    competitors = []
    if refetch_competitors:
        try:
            from .scoring.etsy_market import top_listing_titles
            competitors = top_listing_titles(p["term"], n=10)
        except Exception:
            competitors = []

    def score(k):
        v = p.get(k)
        return f"{v:.2f}" if isinstance(v, (int, float)) else "—"

    L = []
    L.append(f"# Product Report — {p['bundle_type']}  (product #{product_id})\n")
    L.append(f"_Generated {now()} · status: **{p['status']}**_"
             + (f" · [Etsy draft]({etsy['url']})" if etsy else "") + "\n")

    L.append("## 1. Trend signal — why this product exists")
    L.append(f"- **Source trend:** \"{p['term']}\"")
    L.append(f"- **Source:** {p['source']} · **Tier:** {_fmt_tier(p['tier'])}")
    L.append(f"- **Discovered:** {p['discovered_at']}")
    if payload.get("approx_traffic"):
        L.append(f"- **Daily search traffic:** {payload['approx_traffic']} (virality signal)")
    if payload.get("rise_value"):
        L.append(f"- **Rising velocity:** {payload['rise_value']} (% growth / Breakout)")
    if payload.get("geo"):
        L.append(f"- **Geo:** {payload['geo']}")
    if payload.get("seed"):
        L.append(f"- **Seed:** {payload['seed']}")
    L.append("")

    L.append("## 2. Opportunity scores (LLM, 6-factor)")
    L.append("| Virality | Purchase intent | Productization | Competition | Longevity | IP risk | **Composite** |")
    L.append("|---|---|---|---|---|---|---|")
    L.append(f"| {score('virality')} | {score('purchase_intent')} | {score('productization')} "
             f"| {score('competition')} | {score('longevity')} | {score('ip_risk')} | **{score('composite')}** |")
    if p.get("rationale"):
        L.append(f"\n> _Rationale:_ {p['rationale']}")
    L.append("")

    L.append("## 3. Etsy market validation (real data)")
    if p.get("listing_count") is not None:
        L.append(f"- **Competition:** {p['listing_count']} active listings "
                 f"→ competition_score {score('mkt_competition')}")
        L.append(f"- **Demand:** ~{p.get('avg_favorites')} avg favorites on top listings "
                 f"→ demand_score {score('mkt_demand')}")
        if p.get("emerging_shops"):
            L.append(f"- **Emerging niche:** {p['emerging_shops']} small shop(s) "
                     f"climbing fast here → winnable (emerging score {score('emerging_niche')})")
        L.append(f"- **Adjusted score (final rank):** **{score('adjusted_score')}** "
                 f"= 0.40·composite + 0.30·demand + 0.30·beatability + 0.10·emerging")
    else:
        L.append("- _Not market-validated (ranked on LLM composite only)._")
    L.append("")

    L.append("## 4. Competitor signal — what informed the bundle")
    if competitors:
        L.append("_Current top-ranking listings for this keyword (structure learned, never copied):_")
        for c in competitors:
            L.append(f"- {c[:90]}")
    else:
        L.append("- _none captured_")
    L.append("")

    L.append("## 5. Decision")
    L.append("- **Selected** as a top IP-safe, buildable opportunity"
             + (f" (adjusted score {score('adjusted_score')})" if p.get('adjusted_score') else "") + ".")
    L.append(f"- **Bundle:** {p['bundle_type']} — _{p['title_concept']}_")
    L.append(f"- **Components ({len(items)}):**")
    for it in items:
        L.append(f"  - {it.name} ({it.asset_type})")
    L.append("")

    if ds:
        L.append("## 6. Design system")
        L.append(f"- **Aesthetic:** {ds.aesthetic}")
        L.append(f"- **Palette:** {', '.join(json.loads(ds.palette or '[]'))}")
        L.append(f"- **Style:** {ds.style_notes}")
        L.append(f"- **Typography:** {ds.typography}")
        L.append("")

    if assets:
        L.append("## 7. Production QC")
        for a in assets:
            L.append(f"- {a['name']}: {a['qc_status']} ({a['qc_score']:.2f})")
        L.append("")

    if listing:
        L.append("## 8. SEO")
        L.append(f"- **Primary keyword:** {kw.get('primary_keyword', '—')}")
        L.append(f"- **Title:** {listing['title']}")
        L.append(f"- **Tags:** {', '.join(json.loads(listing['tags'] or '[]'))}")
        L.append("")

    L.append("## 9. Audit notes (fill in when reviewing performance)")
    L.append("- Views / favorites / sales after launch: ")
    L.append("- What worked: ")
    L.append("- What to change next iteration: ")
    L.append("")

    out_dir = OUTPUT_DIR / str(product_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "PRODUCT_REPORT.md"
    path.write_text("\n".join(L))
    print(f"[report] wrote {path}")
    return path
