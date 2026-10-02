"""Competitive-intelligence enrichment for stage 03 (VALIDATE), via context.dev.

This is NOT a content source and NOT a scraper for copying listings. For a trend candidate that has
ALREADY cleared upstream scoring (stage 02), it measures how saturated the Etsy market is and asks
the existing LLM what buyer need the top listings FAIL to serve — so the engine builds ORIGINAL
products aimed at unmet demand. Its output attaches to the trend and flows through the normal funnel;
it never bypasses the EV gate (a candidate still clears the gate before any stage-05 image spend).

Two-step data pull (verified live 2026-07):
  1. web.search {query, includeDomains:["etsy.com"]} -> the top Etsy LISTING urls + snippets
     (context.dev's own index; ~1 credit/result). Etsy's SEARCH page itself blocks direct extraction
     (WEBSITE_ACCESS_ERROR), so we go through the index rather than scraping the search page.
  2. web.extract {url, schema:LISTING_SCHEMA} on each top listing PAGE -> structured
     {title, description, tags, price, num_reviews} (the advanced ~10-credit call; works on the
     individual listing pages). This is the deep, structured signal the gap analysis runs on.

ORIGINALITY (the whole point): extracted competitor text is INPUT for analysis only. It is stored in
one clearly-named `competitor_sample` field that the generation/SEO stages never read (structural
separation, see db.get_competitive_intel), and `assert_original()` is a runtime backstop that raises
if any competitor field ever appears verbatim in a generated product's content.

COST CONTROL (non-negotiable): every context.dev call is logged to a per-call credit ledger tagged
`context_dev`; a per-run cap bounds the number of web.extract (~10-credit) calls; a cache (TTL) keeps
us from re-hitting the same query/URL; enrichment is gated on `context_dev_enabled` (ON by default;
set it False to go dark) plus a score threshold and a per-run candidate ceiling, so we pay only for a
bounded number of candidates already worth validating.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import Counter

import requests

from ..config import DATA_DIR, settings

SEARCH_URL = "https://api.context.dev/v1/web/search"
EXTRACT_URL = "https://api.context.dev/v1/web/extract"
SPEND_LOG = DATA_DIR / "context_dev_spend.jsonl"     # per-call credit ledger, source-tagged
CACHE_FILE = DATA_DIR / "context_dev_cache.json"     # key -> {ts, data}: skip re-fetching
# context.dev meters in credits (search ~1/result, extract ~10). USD is a rough ledger estimate;
# credits are the true metered unit and are always logged verbatim.
_USD_PER_CREDIT = 0.001

# JSON Schema the extractor fills for a LISTING page. Only PUBLIC marketplace fields.
LISTING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "price": {"type": "number"},
        "num_reviews": {"type": "integer"},
    },
    "required": ["title"],
}

_GAP_SYSTEM = (
    "You find UNMET buyer demand in a saturated Etsy niche. Given the titles and descriptions of the "
    "top competing listings, name the 1-3 recurring buyer needs these listings FAIL to serve — the "
    "gaps an ORIGINAL new product could win. Describe each gap as a NEED in your own words; never "
    "quote, copy, or lightly reword a competitor's listing. Return STRICT JSON: a list of 1-3 short "
    "strings."
)


class OriginalityViolation(RuntimeError):
    """Raised when competitor text would leak into a generated product's content."""


# ---------------------------------------------------------------- ledger + cache + HTTP

def _record_spend(kind: str, ref: str, credits: float) -> None:
    """Append one context.dev call to the source-tagged credit ledger. Best-effort."""
    line = {"time": int(time.time()), "source": "context_dev", "kind": kind, "ref": ref,
            "credits": credits, "cost_usd": round(credits * _USD_PER_CREDIT, 6)}
    try:
        SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SPEND_LOG.open("a") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError:
        pass


def total_spend() -> dict:
    """Sum the context.dev ledger -> {credits, cost_usd, calls}."""
    credits, usd, n = 0.0, 0.0, 0
    if SPEND_LOG.exists():
        for ln in SPEND_LOG.read_text().splitlines():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            credits += float(d.get("credits") or 0)
            usd += float(d.get("cost_usd") or 0)
            n += 1
    return {"credits": round(credits, 2), "cost_usd": round(usd, 4), "calls": n}


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.context_dev_api_key}", "Content-Type": "application/json"}


def web_search(query: str, *, include_domains: list[str] | None = None,
               max_results: int = 10) -> dict | None:
    """context.dev web.search -> {results:[{title, description, url}], credits}. Fails soft to None."""
    if not settings.context_dev_api_key:
        print("[ctx] skipped: CONTEXT_DEV_API_KEY not set")
        return None
    body: dict = {"query": query}
    if include_domains:
        body["includeDomains"] = include_domains
    try:
        resp = requests.post(SEARCH_URL, headers=_headers(), json=body, timeout=45)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:  # noqa: BLE001 — never raise into validate
        print(f"[ctx] web.search failed for {query!r}: {e}")
        return None
    results = [{"title": str(r.get("title") or ""), "description": str(r.get("description") or ""),
                "url": str(r.get("url") or "")}
               for r in (payload.get("results") or []) if isinstance(r, dict)][:max_results]
    return {"results": results, "credits": float(len(results))}   # ~1 credit/result


def web_extract(url: str, schema: dict, instructions: str | None = None) -> dict | None:
    """context.dev web.extract (advanced, ~10 credits) -> {data, credits}. Fails soft to None.

    Etsy SEARCH pages return WEBSITE_ACCESS_ERROR; individual LISTING pages extract fine."""
    if not settings.context_dev_api_key:
        return None
    body: dict = {"url": url, "schema": schema}
    if instructions:
        body["instructions"] = instructions[:2000]
    try:
        # The advanced call can crawl a few pages and is genuinely slow; enrichment is gated + capped
        # so this latency is bounded per run.
        resp = requests.post(EXTRACT_URL, headers=_headers(), json=body, timeout=120)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:  # noqa: BLE001
        print(f"[ctx] web.extract failed for {url}: {e}")
        return None
    credits = float((payload.get("key_metadata") or {}).get("credits_consumed") or 0)
    return {"data": payload.get("data") or {}, "credits": credits}


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache))
    except OSError:
        pass


# ---------------------------------------------------------------- the enricher

def _title_structure(titles: list[str]) -> str:
    """A STRUCTURAL descriptor of the titles' shape — never their words (e.g. separator + segment
    count). No competitor phrase is ever emitted."""
    if not titles:
        return "unknown"
    sep = "|" if sum("|" in t for t in titles) > len(titles) / 2 else (
        "-" if sum(" - " in t for t in titles) > len(titles) / 2 else "none")
    split_on = sep if sep != "none" else " "
    seg = round(statistics.median([max(len(t.split(split_on)), 1) for t in titles]))
    return f"separator={sep}, ~{seg} segments"


class CompetitiveEnricher:
    """Per-validate-run enricher. Holds the web.extract budget + a query/URL cache so one run can
    enrich a few high-scoring candidates without re-paying or blowing the cap."""

    def __init__(self, *, cap: int | None = None, ttl_hours: float | None = None,
                 min_score: float | None = None, per_candidate: int | None = None,
                 max_enrich: int | None = None):
        self.cap = settings.context_dev_extract_cap if cap is None else cap
        ttl_h = settings.context_dev_cache_ttl_hours if ttl_hours is None else ttl_hours
        self.ttl_s = ttl_h * 3600.0
        self.min_score = settings.context_dev_enrich_min_score if min_score is None else min_score
        self.per_candidate = (settings.context_dev_results_per_search
                              if per_candidate is None else per_candidate)
        # Hard per-run ceiling on how many CANDIDATES we pay to enrich. This bounds web.SEARCH spend
        # (which is otherwise uncapped and scales with candidate count), not just web.extract.
        self.max_enrich = settings.context_dev_max_enrich if max_enrich is None else max_enrich
        self.extract_calls = 0                    # web.extract (~10-credit) calls this run
        self.enriched = 0                         # candidates we've paid to enrich this run
        self._cache = _load_cache()

    def _cached(self, key: str):
        hit = self._cache.get(key)
        if hit and (time.time() - float(hit.get("ts", 0))) < self.ttl_s:
            return hit["data"]
        return None

    def _put(self, key: str, data) -> None:
        self._cache[key] = {"ts": time.time(), "data": data}
        _save_cache(self._cache)

    def _gather(self, term: str) -> list[dict]:
        """web.search Etsy -> top listing urls, then web.extract each listing page (cap-bounded).
        Falls back to the search snippets if nothing could be extracted, so gap analysis still runs."""
        skey = "search:" + term.lower()
        search = self._cached(skey)
        if search is None:
            out = web_search(term, include_domains=["etsy.com"], max_results=self.per_candidate * 3)
            if out is None:
                return []
            search = out["results"]
            _record_spend("web.search", term, out["credits"])
            self._put(skey, search)

        listings: list[dict] = []
        for r in [x for x in search if "/listing/" in (x.get("url") or "")][: self.per_candidate]:
            url = r["url"]
            cached = self._cached("extract:" + url)
            if cached is not None:
                listings.append(cached)
                continue
            if self.extract_calls >= self.cap:
                print(f"[ctx] web.extract cap {self.cap} reached — using search snippets")
                break
            out = web_extract(url, LISTING_SCHEMA,
                              instructions="Extract this Etsy listing's public fields.")
            self.extract_calls += 1
            if out is None:
                continue
            _record_spend("web.extract", url, out["credits"])
            self._put("extract:" + url, out["data"])
            listings.append(out["data"])

        if not listings:                          # cap hit or pages blocked: snippets still have signal
            listings = [{"title": r.get("title", ""), "description": r.get("description", ""),
                         "tags": [], "price": None} for r in search[: self.per_candidate]]
        return listings

    def enrich(self, term: str, score: float, market_intel: dict | None = None) -> dict | None:
        """Return a market_intel block for `term`, or None when gated off/capped/failed.

        Gate: the enabled flag + only candidates whose stage-02 score cleared the threshold, capped at
        `max_enrich` candidates per run.
        Saturation reuses the free Etsy-API `market_intel` when provided (extending stage 03, not a
        parallel path); context.dev supplies the top-listing text the gap analysis runs on.
        """
        if not settings.context_dev_enabled:
            return None
        if score < self.min_score:
            return None
        if self.enriched >= self.max_enrich:      # per-run spend ceiling (bounds web.search too)
            return None
        self.enriched += 1
        listings = self._gather(term)
        if not listings:
            return None

        titles = [str(lg.get("title") or "").strip() for lg in listings if lg.get("title")]
        descs = [str(lg.get("description") or "").strip() for lg in listings if lg.get("description")]
        tags = [str(t).strip() for lg in listings for t in (lg.get("tags") or []) if str(t).strip()]
        prices = [float(lg["price"]) for lg in listings if isinstance(lg.get("price"), (int, float))]

        mi = market_intel or {}
        saturation = {
            "listing_count": int(mi["count"]) if mi.get("count") is not None else None,
            "price_median": mi.get("median_price")
            or (round(statistics.median(prices), 2) if prices else None),
            "top_tags": (mi.get("top_tags") or [t for t, _ in Counter(tags).most_common(10)])[:10],
        }
        tag_counts = [len(lg.get("tags") or []) for lg in listings if lg.get("tags")]
        seo_pattern = {
            "title_len_median": int(statistics.median([len(t) for t in titles])) if titles else 0,
            "tag_count_range": ([min(tag_counts), max(tag_counts)] if tag_counts else [0, 0]),
            "common_title_structure": _title_structure(titles),
        }
        return {
            "saturation": saturation,
            "gap_analysis": _gap_analysis(titles, descs),
            "seo_pattern": seo_pattern,
            # ANALYSIS ONLY — never read by generation/SEO. Kept for auditability + the guard.
            "competitor_sample": {"titles": titles[:12], "descriptions": descs[:12], "tags": tags[:40]},
        }


def _gap_analysis(titles: list[str], descriptions: list[str] | None = None) -> list[str]:
    """Ask the EXISTING LLM (Sonnet 5) for 1-3 unmet buyer needs. Original description of the gap —
    the model is told never to quote competitors. Fails soft to []."""
    if not titles:
        return []
    descriptions = descriptions or []
    lines = []
    for i, t in enumerate(titles[:15]):
        d = descriptions[i][:200] if i < len(descriptions) else ""
        lines.append(f"- {t}" + (f" — {d}" if d else ""))
    try:
        from .. import llm
        out = llm.complete_json(_GAP_SYSTEM, "Top competing listings:\n" + "\n".join(lines),
                                max_tokens=400)
    except Exception as e:  # noqa: BLE001
        print(f"[ctx] gap analysis skipped: {e}")
        return []
    if isinstance(out, dict):
        for v in out.values():
            if isinstance(v, list):
                out = v
                break
    if not isinstance(out, list):
        return []
    return [str(s).strip() for s in out if str(s).strip()][:3]


# ---------------------------------------------------------------- originality guard

def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().split())


def assert_original(product_content: dict, block: dict | None) -> None:
    """Backstop for the originality rule: raise if any competitor field (title/description/tag from
    the analysis-only `competitor_sample`) appears verbatim in a generated product's content fields
    (title, description, tags). Generation never reads competitor_sample structurally; this catches a
    regression if it ever did."""
    sample = (block or {}).get("competitor_sample") or {}
    competitor = {_norm(x) for x in
                  (sample.get("titles") or []) + (sample.get("tags") or []) +
                  (sample.get("descriptions") or []) if _norm(x)}
    if not competitor:
        return
    fields = []
    for key in ("title", "description"):
        if product_content.get(key):
            fields.append(_norm(product_content[key]))
    fields += [_norm(t) for t in (product_content.get("tags") or [])]
    for f in fields:
        for c in competitor:
            # Flag a WHOLE competitor field copied verbatim (c == f), or a LONG competitor span (a
            # full title/sentence, >40 chars) embedded verbatim. A short (<=40 char) substring match
            # is ordinary shared niche vocabulary ('celebration of life program'), not a leak.
            if c and (c == f or (len(c) > 40 and c in f)):
                raise OriginalityViolation(
                    f"competitor text leaked into product content: {c[:60]!r}")
