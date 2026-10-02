"""SQLite access layer. One file, easy to inspect with any SQLite browser."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator

from pathlib import Path

from .config import OUTPUT_DIR, ROOT, settings
from .models import (
    Asset, BundleItem, DesignSystem, Listing, Mockup, Product, Score, Trend,
)


def resolve_output_path(stored: str, product_id: int | None = None) -> str:
    """Map a stored asset/mockup path to a valid absolute path under this repo.

    Paths are persisted relative-to-ROOT going forward, but historical rows hold
    absolute strings from before the repo moved (e.g. /home/me/old-checkout/...).
    Resolution order: (1) relative path -> ROOT/<rel>; (2) absolute that exists ->
    as-is; (3) stale absolute -> rebuild under OUTPUT_DIR from the '/output/...'
    tail (or, as a last resort, OUTPUT_DIR/<pid>/<basename>). Never raises.
    """
    if not stored:
        return stored
    p = Path(stored)
    if not p.is_absolute():
        return str((ROOT / p).resolve())
    if p.exists():
        return stored
    parts = p.parts
    if "output" in parts:                       # rebuild from the /output/... tail
        tail = Path(*parts[parts.index("output") + 1:])
        cand = OUTPUT_DIR / tail
        if cand.exists() or product_id is None:
            return str(cand)
    if product_id is not None:
        return str(OUTPUT_DIR / str(product_id) / p.name)
    return stored

SCHEMA = """
CREATE TABLE IF NOT EXISTS trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    term TEXT NOT NULL,
    raw_payload TEXT DEFAULT '',
    tier INTEGER DEFAULT 1,
    discovered_at TEXT NOT NULL,
    UNIQUE(source, term)
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id INTEGER NOT NULL REFERENCES trends(id),
    virality REAL, purchase_intent REAL, productization REAL,
    competition REAL, longevity REAL, ip_risk REAL,
    composite REAL, rationale TEXT, scored_at TEXT,
    UNIQUE(trend_id)
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id INTEGER NOT NULL REFERENCES trends(id),
    title_concept TEXT NOT NULL,
    bundle_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    format TEXT NOT NULL DEFAULT 'pdf',   -- 'pdf' (print-at-home bundle) | 'canva' (editable suite)
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bundle_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    name TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    spec TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS design_systems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    palette TEXT DEFAULT '[]',
    style_notes TEXT DEFAULT '',
    icon_style TEXT DEFAULT '',
    aesthetic TEXT DEFAULT '',
    typography TEXT DEFAULT '',
    UNIQUE(product_id)
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_item_id INTEGER NOT NULL REFERENCES bundle_items(id),
    prompt TEXT DEFAULT '',
    file_path TEXT NOT NULL,
    qc_status TEXT DEFAULT 'pending',
    qc_score REAL DEFAULT 0.0,
    qc_notes TEXT DEFAULT '',
    variations INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(bundle_item_id)
);

CREATE TABLE IF NOT EXISTS mockups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    kind TEXT NOT NULL,
    prompt TEXT DEFAULT '',
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(product_id, kind)
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    title TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    description TEXT DEFAULT '',
    alt_texts TEXT DEFAULT '[]',
    faq TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(product_id)
);

CREATE TABLE IF NOT EXISTS keyword_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(product_id)
);

CREATE TABLE IF NOT EXISTS product_intel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    archetype TEXT NOT NULL DEFAULT 'planner',
    median_price REAL,
    top_tags TEXT DEFAULT '[]',
    intel TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(product_id)
);

CREATE TABLE IF NOT EXISTS etsy_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    etsy_listing_id INTEGER NOT NULL,
    url TEXT DEFAULT '',
    state TEXT DEFAULT 'draft',
    created_at TEXT NOT NULL,
    renewed_at TEXT DEFAULT '',
    is_seasonal INTEGER DEFAULT 0,
    season TEXT DEFAULT '',
    marked_for_deactivation INTEGER DEFAULT 0,
    marked_at TEXT DEFAULT '',
    UNIQUE(product_id)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etsy_listing_id INTEGER NOT NULL,
    views INTEGER DEFAULT 0,
    favorites INTEGER DEFAULT 0,
    sales INTEGER DEFAULT 0,
    pulled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

-- Competitive-intelligence enrichment (stage 03, context.dev). ANALYSIS ONLY: `competitor_sample`
-- holds raw competitor text used purely to derive gaps/patterns; the generation + SEO stages NEVER
-- query this table, so no competitor field can flow into a product's content (originality guard).
CREATE TABLE IF NOT EXISTS competitive_intel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id INTEGER NOT NULL REFERENCES trends(id),
    saturation TEXT DEFAULT '{}',          -- listing_count, price_median, top_tags (aggregate stats)
    gap_analysis TEXT DEFAULT '[]',        -- 1-3 ORIGINAL unmet-need strings (LLM output)
    seo_pattern TEXT DEFAULT '{}',         -- structural patterns only (lengths/ranges/shape)
    competitor_sample TEXT DEFAULT '{}',   -- ANALYSIS-ONLY raw competitor text; generation never reads
    created_at TEXT NOT NULL,
    UNIQUE(trend_id)
);

CREATE TABLE IF NOT EXISTS market_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_id INTEGER NOT NULL REFERENCES trends(id),
    listing_count INTEGER DEFAULT 0,
    avg_favorites REAL DEFAULT 0,
    competition_score REAL DEFAULT 0,
    demand_score REAL DEFAULT 0,
    adjusted_score REAL DEFAULT 0,
    checked_at TEXT NOT NULL,
    UNIQUE(trend_id)
);

CREATE TABLE IF NOT EXISTS listing_keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    etsy_listing_id INTEGER NOT NULL,
    keyword TEXT NOT NULL,
    is_primary INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(product_id, etsy_listing_id, keyword)
);

CREATE TABLE IF NOT EXISTS rank_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    etsy_listing_id INTEGER NOT NULL,
    keyword TEXT NOT NULL,
    rank INTEGER,
    total_results INTEGER DEFAULT 0,
    result_count INTEGER DEFAULT 0,
    page INTEGER DEFAULT 1,
    found INTEGER DEFAULT 0,
    pulled_at TEXT NOT NULL
);

-- Keyword pulse: daily snapshots of a tracked keyword's TOP LISTINGS' view/fav
-- counters. Deltas between snapshots of the SAME listing give true CURRENT
-- demand velocity (market_intel's avg_daily_views is a lifetime average and
-- systematically misreads old listings; single snapshots are also sample-noisy).
CREATE TABLE IF NOT EXISTS keyword_pulse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL,
    listing_id INTEGER NOT NULL,
    views INTEGER DEFAULT 0,
    favorites INTEGER DEFAULT 0,
    captured_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pulse_kw ON keyword_pulse(keyword, listing_id, captured_at);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# Columns added after the original schema shipped. Each is applied idempotently
# to already-existing databases (init_db only CREATEs tables IF NOT EXISTS, so it
# never alters a table that already has rows — like the live shop's engine.db).
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "etsy_listings": [
        ("renewed_at", "TEXT DEFAULT ''"),
        ("is_seasonal", "INTEGER DEFAULT 0"),
        ("season", "TEXT DEFAULT ''"),
        # `prune` marks unproven-after-30-days listings for deactivation (DB flag only; a human
        # deactivates on Etsy). Back-filled to 0 on existing DBs.
        ("marked_for_deactivation", "INTEGER DEFAULT 0"),
        ("marked_at", "TEXT DEFAULT ''"),
    ],
    # Emerging-niche signal (Bahattin: a small shop climbing fast = winnable).
    "market_signals": [
        ("emerging_niche", "REAL DEFAULT 0"),
        ("emerging_shops", "INTEGER DEFAULT 0"),
    ],
    # Captured live listing price per snapshot, so the P&L has a durable price
    # history (metrics.pull_metrics fills it; scripts/pnl_report.py reads it).
    "metrics": [
        ("price", "REAL DEFAULT 0"),
    ],
    # The Canva-editable line became a first-class DB product (was JSONL ledgers); existing DBs
    # predate the column, so back-fill it defaulting to the print-at-home 'pdf' line.
    "products": [
        ("format", "TEXT NOT NULL DEFAULT 'pdf'"),
    ],
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


# --- Trends ---

def upsert_trend(t: Trend) -> int:
    """Insert a trend; ignore if (source, term) already seen. Returns its id."""
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO trends (source, term, raw_payload, tier, discovered_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(source, term) DO UPDATE SET raw_payload=excluded.raw_payload
               RETURNING id""",
            (t.source, t.term, t.raw_payload, int(t.tier), t.discovered_at),
        )
        return cur.fetchone()["id"]


def unscored_trends() -> list[Trend]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT t.* FROM trends t
               LEFT JOIN scores s ON s.trend_id = t.id
               WHERE s.id IS NULL"""
        ).fetchall()
    return [_row_to_trend(r) for r in rows]


def _row_to_trend(r: sqlite3.Row) -> Trend:
    return Trend(
        id=r["id"], source=r["source"], term=r["term"],
        raw_payload=r["raw_payload"], tier=r["tier"],
        discovered_at=r["discovered_at"],
    )


# --- Scores ---

def upsert_score(s: Score) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO scores
               (trend_id, virality, purchase_intent, productization, competition,
                longevity, ip_risk, composite, rationale, scored_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(trend_id) DO UPDATE SET
                 virality=excluded.virality, purchase_intent=excluded.purchase_intent,
                 productization=excluded.productization, competition=excluded.competition,
                 longevity=excluded.longevity, ip_risk=excluded.ip_risk,
                 composite=excluded.composite, rationale=excluded.rationale,
                 scored_at=excluded.scored_at""",
            (s.trend_id, s.virality, s.purchase_intent, s.productization,
             s.competition, s.longevity, s.ip_risk, s.composite, s.rationale,
             s.scored_at),
        )


def top_opportunities(limit: int, max_ip_risk: float = 0.25) -> list[dict]:
    """Best scored trends that pass the IP-risk gate, joined with their term.

    Ranks by the market-adjusted score when Etsy validation exists, else by the
    LLM composite. Market fields are included when present.
    """
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.*, t.term, t.source, t.tier,
                      m.listing_count, m.avg_favorites,
                      m.competition_score AS mkt_competition,
                      m.demand_score AS mkt_demand, m.adjusted_score,
                      COALESCE(m.adjusted_score, s.composite) AS rank_score
               FROM scores s
               JOIN trends t ON t.id = s.trend_id
               LEFT JOIN market_signals m ON m.trend_id = s.trend_id
               WHERE s.ip_risk <= ?
               ORDER BY rank_score DESC
               LIMIT ?""",
            (max_ip_risk, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_market_signal(trend_id: int, sig: dict, adjusted_score: float) -> None:
    from .models import now
    with connect() as conn:
        conn.execute(
            """INSERT INTO market_signals
               (trend_id, listing_count, avg_favorites, competition_score,
                demand_score, adjusted_score, emerging_niche, emerging_shops,
                checked_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(trend_id) DO UPDATE SET
                 listing_count=excluded.listing_count,
                 avg_favorites=excluded.avg_favorites,
                 competition_score=excluded.competition_score,
                 demand_score=excluded.demand_score,
                 adjusted_score=excluded.adjusted_score,
                 emerging_niche=excluded.emerging_niche,
                 emerging_shops=excluded.emerging_shops,
                 checked_at=excluded.checked_at""",
            (trend_id, sig["count"], sig["avg_favorites"], sig["competition_score"],
             sig["demand_score"], adjusted_score,
             float(sig.get("emerging_niche", 0.0)), int(sig.get("emerging_shops", 0)),
             now()),
        )


# --- Products ---

def insert_product(p: Product) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO products (trend_id, title_concept, bundle_type, status, format, created_at)
               VALUES (?,?,?,?,?,?) RETURNING id""",
            (p.trend_id, p.title_concept, p.bundle_type, p.status,
             getattr(p, "format", "pdf"), p.created_at),
        )
        return cur.fetchone()["id"]


def route_to_canva(trend_id: int, term: str) -> int:
    """Record a Canva-routed trend as a DB product awaiting production (status='routed'). The DB is
    now the queue (replacing the parallel JSONL); deduped by trend so re-running architect is a no-op."""
    from .models import Product
    with connect() as conn:
        row = conn.execute("SELECT id FROM products WHERE trend_id=? AND format='canva'",
                           (trend_id,)).fetchone()
        if row:
            return row["id"]
    return insert_product(Product(trend_id=trend_id, title_concept=term, bundle_type=term,
                                  status="routed", format="canva"))


def pending_canva_products() -> list[dict]:
    """Canva products routed but not yet produced (status='routed'), with the trend term."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT p.id AS product_id, t.term FROM products p JOIN trends t ON t.id = p.trend_id
               WHERE p.format='canva' AND p.status='routed' ORDER BY p.id DESC""").fetchall()
    return [dict(r) for r in rows]


def save_canva_product(niche: str, product_kind: str, pieces: list[dict], listing: dict,
                       product_id: int | None = None) -> int:
    """Persist a Canva suite as a FIRST-CLASS DB product (format='canva'), the same shape the PDF
    line uses: a trend + products row + bundle_items (the pieces) + a listings row. If `product_id`
    is given (a trend the architect already routed to Canva), fill THAT product in place instead of
    creating a duplicate. Returns the product_id so the manifest/publish/learning can reference it."""
    from .models import BundleItem, Listing, Product, Trend
    if product_id is None:
        tid = upsert_trend(Trend(source="canva", term=niche))
        product_id = insert_product(Product(trend_id=tid, title_concept=product_kind,
                                            bundle_type=product_kind, status="planned", format="canva"))
    else:
        with connect() as conn:      # fill the routed product; clear stale items so re-prepare is idempotent
            conn.execute("UPDATE products SET title_concept=?, bundle_type=?, status='planned' WHERE id=?",
                         (product_kind, product_kind, product_id))
            conn.execute("DELETE FROM bundle_items WHERE product_id=?", (product_id,))
    for pc in pieces:
        insert_bundle_item(BundleItem(product_id=product_id,
                                      name=(pc.get("name") or pc.get("title") or "page"),
                                      asset_type="canva_page", spec=pc.get("use") or ""))
    upsert_listing(Listing(product_id=product_id, title=listing.get("title", ""),
                           tags=json.dumps(listing.get("tags") or [], ensure_ascii=False),
                           description=listing.get("description", ""),
                           alt_texts=json.dumps(listing.get("alt_texts") or [], ensure_ascii=False)))
    return product_id


def insert_bundle_item(b: BundleItem) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO bundle_items (product_id, name, asset_type, spec)
               VALUES (?,?,?,?) RETURNING id""",
            (b.product_id, b.name, b.asset_type, b.spec),
        )
        return cur.fetchone()["id"]


def products_with_items() -> list[dict]:
    with connect() as conn:
        prods = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
        out = []
        for p in prods:
            items = conn.execute(
                "SELECT id, name, asset_type, spec FROM bundle_items WHERE product_id=?",
                (p["id"],),
            ).fetchall()
            d = dict(p)
            d["items"] = [dict(i) for i in items]
            out.append(d)
    return out


def provenance(product_id: int) -> dict:
    """Everything behind a product's existence: trend + scores + market signal."""
    with connect() as conn:
        r = conn.execute(
            """SELECT p.id AS product_id, p.bundle_type, p.title_concept, p.status,
                      p.created_at,
                      t.term, t.source, t.tier, t.raw_payload, t.discovered_at,
                      s.virality, s.purchase_intent, s.productization, s.competition,
                      s.longevity, s.ip_risk, s.composite, s.rationale,
                      m.listing_count, m.avg_favorites, m.competition_score AS mkt_competition,
                      m.demand_score AS mkt_demand, m.adjusted_score,
                      m.emerging_niche, m.emerging_shops
               FROM products p
               JOIN trends t ON t.id = p.trend_id
               LEFT JOIN scores s ON s.trend_id = p.trend_id
               LEFT JOIN market_signals m ON m.trend_id = p.trend_id
               WHERE p.id=?""",
            (product_id,),
        ).fetchone()
    return dict(r) if r else {}


def products_by_status(status: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM products WHERE status=? ORDER BY id", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


def product_terms() -> list[dict]:
    """Every product's trend term (ANY status: produced/planned/routed), for theme-based dedup of
    in-flight products that aren't in the produced-history yet."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.trend_id, p.status, p.format, t.term "
            "FROM products p JOIN trends t ON t.id = p.trend_id"
        ).fetchall()
    return [dict(r) for r in rows]


def pending_approval() -> list[dict]:
    """Products the architect ROUTED but has not produced — the human-approval queue.

    PDF products land in 'planned' (ready to generate); Canva products land in 'routed' (ready for a
    design set + Magic Layers). Each row carries its format, term, bundle concept and the number of
    planned pieces, plus the context.dev gap_analysis when stage 03 enriched it — everything the owner
    needs to approve or skip a product BEFORE any image spend.
    """
    with connect() as conn:
        rows = conn.execute(
            """SELECT p.id, p.format, p.status, p.bundle_type, p.title_concept, p.trend_id,
                      t.term,
                      (SELECT COUNT(*) FROM bundle_items bi WHERE bi.product_id = p.id) AS pieces,
                      ci.gap_analysis
               FROM products p
               JOIN trends t ON t.id = p.trend_id
               LEFT JOIN competitive_intel ci ON ci.trend_id = p.trend_id
               WHERE (p.format='pdf' AND p.status='planned')
                  OR (p.format='canva' AND p.status='routed')
               ORDER BY p.format, p.id""",
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["gap_analysis"] = json.loads(d.get("gap_analysis") or "[]")
        out.append(d)
    return out


def bundle_items_for(product_id: int) -> list[BundleItem]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM bundle_items WHERE product_id=?", (product_id,)
        ).fetchall()
    return [BundleItem(id=r["id"], product_id=r["product_id"], name=r["name"],
                       asset_type=r["asset_type"], spec=r["spec"]) for r in rows]


def bundle_item(item_id: int) -> BundleItem | None:
    """One bundle item by id (for surgical single-asset regen)."""
    with connect() as conn:
        r = conn.execute("SELECT * FROM bundle_items WHERE id=?", (item_id,)).fetchone()
    return BundleItem(id=r["id"], product_id=r["product_id"], name=r["name"],
                      asset_type=r["asset_type"], spec=r["spec"]) if r else None


def product(product_id: int) -> dict | None:
    """One product row as a dict by id."""
    with connect() as conn:
        r = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    return dict(r) if r else None


def set_product_status(product_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE products SET status=? WHERE id=?", (status, product_id))


# --- Design systems ---

def upsert_design_system(d: DesignSystem) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO design_systems
               (product_id, palette, style_notes, icon_style, aesthetic, typography)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(product_id) DO UPDATE SET
                 palette=excluded.palette, style_notes=excluded.style_notes,
                 icon_style=excluded.icon_style, aesthetic=excluded.aesthetic,
                 typography=excluded.typography""",
            (d.product_id, d.palette, d.style_notes, d.icon_style, d.aesthetic,
             d.typography),
        )


def get_design_system(product_id: int) -> DesignSystem | None:
    with connect() as conn:
        r = conn.execute(
            "SELECT * FROM design_systems WHERE product_id=?", (product_id,)
        ).fetchone()
    if not r:
        return None
    return DesignSystem(
        id=r["id"], product_id=r["product_id"], palette=r["palette"],
        style_notes=r["style_notes"], icon_style=r["icon_style"],
        aesthetic=r["aesthetic"], typography=r["typography"],
    )


# --- Assets ---

def upsert_asset(a: Asset) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO assets
               (bundle_item_id, prompt, file_path, qc_status, qc_score, qc_notes,
                variations, created_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(bundle_item_id) DO UPDATE SET
                 prompt=excluded.prompt, file_path=excluded.file_path,
                 qc_status=excluded.qc_status, qc_score=excluded.qc_score,
                 qc_notes=excluded.qc_notes, variations=excluded.variations,
                 created_at=excluded.created_at""",
            (a.bundle_item_id, a.prompt, a.file_path, a.qc_status, a.qc_score,
             a.qc_notes, a.variations, a.created_at),
        )


def assets_for_product(product_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT a.*, b.name, b.asset_type FROM assets a
               JOIN bundle_items b ON b.id = a.bundle_item_id
               WHERE b.product_id=? ORDER BY a.id""",
            (product_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["file_path"] = resolve_output_path(d.get("file_path", ""), product_id)
        out.append(d)
    return out


# --- Mockups ---

def upsert_mockup(m: Mockup) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO mockups (product_id, kind, prompt, file_path, created_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(product_id, kind) DO UPDATE SET
                 prompt=excluded.prompt, file_path=excluded.file_path,
                 created_at=excluded.created_at""",
            (m.product_id, m.kind, m.prompt, m.file_path, m.created_at),
        )


def mockups_for_product(product_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM mockups WHERE product_id=? ORDER BY id", (product_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["file_path"] = resolve_output_path(d.get("file_path", ""), product_id)
        out.append(d)
    return out


# --- Listings (SEO) ---

def upsert_listing(listing: Listing) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO listings
               (product_id, title, tags, description, alt_texts, faq, created_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(product_id) DO UPDATE SET
                 title=excluded.title, tags=excluded.tags,
                 description=excluded.description, alt_texts=excluded.alt_texts,
                 faq=excluded.faq, created_at=excluded.created_at""",
            (listing.product_id, listing.title, listing.tags, listing.description,
             listing.alt_texts, listing.faq, listing.created_at),
        )


def get_listing(product_id: int) -> dict | None:
    with connect() as conn:
        r = conn.execute(
            "SELECT * FROM listings WHERE product_id=?", (product_id,)
        ).fetchone()
    return dict(r) if r else None


# --- Keyword research ---

def upsert_keyword_set(product_id: int, data: dict) -> None:
    from .models import now
    with connect() as conn:
        conn.execute(
            """INSERT INTO keyword_sets (product_id, data, created_at)
               VALUES (?,?,?)
               ON CONFLICT(product_id) DO UPDATE SET
                 data=excluded.data, created_at=excluded.created_at""",
            (product_id, json.dumps(data, ensure_ascii=False), now()),
        )


def get_keyword_set(product_id: int) -> dict | None:
    with connect() as conn:
        r = conn.execute(
            "SELECT data FROM keyword_sets WHERE product_id=?", (product_id,)
        ).fetchone()
    return json.loads(r["data"]) if r else None


# --- Product market intelligence (archetype, real tags, niche price) ---

def upsert_product_intel(product_id: int, archetype: str, median_price,
                         top_tags: list, intel: dict) -> None:
    from .models import now
    with connect() as conn:
        conn.execute(
            """INSERT INTO product_intel
               (product_id, archetype, median_price, top_tags, intel, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(product_id) DO UPDATE SET
                 archetype=excluded.archetype, median_price=excluded.median_price,
                 top_tags=excluded.top_tags, intel=excluded.intel,
                 created_at=excluded.created_at""",
            (product_id, archetype, median_price,
             json.dumps(top_tags or [], ensure_ascii=False),
             json.dumps(intel or {}, ensure_ascii=False), now()),
        )


def get_product_intel(product_id: int) -> dict | None:
    with connect() as conn:
        r = conn.execute(
            "SELECT archetype, median_price, top_tags, intel FROM product_intel "
            "WHERE product_id=?", (product_id,)
        ).fetchone()
    if not r:
        return None
    return {
        "archetype": r["archetype"],
        "median_price": r["median_price"],
        "top_tags": json.loads(r["top_tags"] or "[]"),
        "intel": json.loads(r["intel"] or "{}"),
    }


# --- Etsy listings (published drafts) ---

def upsert_etsy_listing(product_id: int, etsy_listing_id: int, url: str,
                        state: str = "draft", is_seasonal: bool = False,
                        season: str = "") -> None:
    from .models import now
    with connect() as conn:
        conn.execute(
            """INSERT INTO etsy_listings
               (product_id, etsy_listing_id, url, state, created_at,
                is_seasonal, season)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(product_id) DO UPDATE SET
                 etsy_listing_id=excluded.etsy_listing_id, url=excluded.url,
                 state=excluded.state, is_seasonal=excluded.is_seasonal,
                 season=excluded.season""",
            (product_id, etsy_listing_id, url, state, now(),
             1 if is_seasonal else 0, season),
        )


def set_listing_state(etsy_listing_id: int, state: str) -> None:
    """Sync the REAL Etsy listing state (active/draft/expired/sold_out...) back
    into the local row. Publisher writes 'draft' once and nothing used to update
    it, so the local DB claimed everything was a draft forever."""
    if not state:
        return
    with connect() as conn:
        conn.execute(
            "UPDATE etsy_listings SET state=? WHERE etsy_listing_id=?",
            (state, etsy_listing_id),
        )


def product_status_for_listing_state(state: str, current_status: str) -> str | None:
    """Map Etsy's live state to the local pipeline lifecycle.

    Etsy returns ``edit`` for listings that are editable but not active. Once a
    listing exists on Etsy it must never remain in an asset-generation queue.
    Deliberately deleted local products stay deleted unless Etsy says they are
    actually active, in which case the shop is the source of truth.
    """
    normalized = (state or "").lower()
    if normalized == "active":
        return "published"
    if normalized in {"draft", "edit"} and current_status != "deleted":
        return "drafted"
    return None


def sync_product_status_from_listing(etsy_listing_id: int, state: str) -> str | None:
    """Sync the product lifecycle from its real Etsy listing state."""
    if not state:
        return None
    with connect() as conn:
        row = conn.execute(
            """SELECT p.id, p.status
               FROM products p
               JOIN etsy_listings e ON e.product_id=p.id
               WHERE e.etsy_listing_id=?""",
            (etsy_listing_id,),
        ).fetchone()
        if not row:
            return None
        status = product_status_for_listing_state(state, row["status"])
        if status and status != row["status"]:
            conn.execute("UPDATE products SET status=? WHERE id=?", (status, row["id"]))
        return status


def mark_listing_renewed(etsy_listing_id: int) -> None:
    """Record that a listing was just refreshed/renewed on Etsy."""
    from .models import now
    with connect() as conn:
        conn.execute(
            "UPDATE etsy_listings SET renewed_at=? WHERE etsy_listing_id=?",
            (now(), etsy_listing_id),
        )


def seasonal_listings() -> list[dict]:
    """Live listings tagged seasonal — the keep-alive registry (never delete)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM etsy_listings WHERE is_seasonal=1 ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_etsy_listing(product_id: int) -> dict | None:
    with connect() as conn:
        r = conn.execute(
            "SELECT * FROM etsy_listings WHERE product_id=?", (product_id,)
        ).fetchone()
    return dict(r) if r else None


def all_etsy_listings() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM etsy_listings ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def products_with_listings() -> list[dict]:
    """Products that have an Etsy listing, with listing + SEO data attached."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT p.id AS product_id, p.title_concept, p.bundle_type,
                      el.etsy_listing_id, el.url, el.state,
                      l.title AS listing_title, l.description
               FROM etsy_listings el
               JOIN products p ON p.id = el.product_id
               LEFT JOIN listings l ON l.product_id = p.id
               ORDER BY p.id"""
        ).fetchall()
    return [dict(r) for r in rows]


# --- Metrics (Faz 5) ---

def insert_metric(etsy_listing_id: int, views: int, favorites: int, sales: int,
                  price: float = 0.0) -> None:
    from .models import now
    with connect() as conn:
        conn.execute(
            """INSERT INTO metrics (etsy_listing_id, views, favorites, sales, price, pulled_at)
               VALUES (?,?,?,?,?,?)""",
            (etsy_listing_id, views, favorites, sales, price, now()),
        )


def latest_metrics() -> list[dict]:
    """Most recent metric row per listing, joined to product + design + trend."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT m.*, e.product_id, p.bundle_type, t.source AS trend_source,
                      t.term, t.tier, d.aesthetic,
                      sc.virality, sc.purchase_intent, sc.productization,
                      sc.competition, sc.longevity,
                      COALESCE(pi.archetype, 'planner') AS archetype
               FROM metrics m
               JOIN (SELECT etsy_listing_id, MAX(pulled_at) AS mx
                     FROM metrics GROUP BY etsy_listing_id) last
                 ON last.etsy_listing_id = m.etsy_listing_id AND last.mx = m.pulled_at
               JOIN etsy_listings e ON e.etsy_listing_id = m.etsy_listing_id
               JOIN products p ON p.id = e.product_id
               LEFT JOIN trends t ON t.id = p.trend_id
               LEFT JOIN design_systems d ON d.product_id = p.id
               LEFT JOIN scores sc ON sc.trend_id = p.trend_id
               LEFT JOIN product_intel pi ON pi.product_id = p.id"""
        ).fetchall()
    return [dict(r) for r in rows]


def active_listings_with_metrics() -> list[dict]:
    """Every ACTIVE Etsy listing with its latest metric snapshot + age fields, for prune analysis.

    Left-joins the most recent metrics row (views/favorites/sales default 0 when never pulled) and
    carries `created_at` (when we recorded the listing == its age proxy) and the deactivation flag.
    """
    with connect() as conn:
        rows = conn.execute(
            """SELECT el.etsy_listing_id, el.product_id, el.created_at, el.state,
                      el.marked_for_deactivation,
                      COALESCE(l.title, p.bundle_type) AS title,
                      COALESCE(m.views, 0) AS views,
                      COALESCE(m.favorites, 0) AS favorites,
                      COALESCE(m.sales, 0) AS sales
               FROM etsy_listings el
               JOIN products p ON p.id = el.product_id
               LEFT JOIN listings l ON l.product_id = p.id
               LEFT JOIN (
                   SELECT m1.etsy_listing_id, m1.views, m1.favorites, m1.sales
                   FROM metrics m1
                   JOIN (SELECT etsy_listing_id, MAX(pulled_at) AS mx
                         FROM metrics GROUP BY etsy_listing_id) last
                     ON last.etsy_listing_id = m1.etsy_listing_id AND last.mx = m1.pulled_at
               ) m ON m.etsy_listing_id = el.etsy_listing_id
               WHERE el.state = 'active'
               ORDER BY el.product_id"""
        ).fetchall()
    return [dict(r) for r in rows]


def mark_listing_for_deactivation(etsy_listing_id: int) -> None:
    """Flag a listing for deactivation (DB only — never touches Etsy). Reversible; a human acts on it."""
    from .models import now
    with connect() as conn:
        conn.execute(
            "UPDATE etsy_listings SET marked_for_deactivation=1, marked_at=? WHERE etsy_listing_id=?",
            (now(), etsy_listing_id),
        )


# --- Competitive intelligence (stage 03 enrichment; analysis-only) ---

def upsert_competitive_intel(trend_id: int, block: dict) -> None:
    """Store a trend's market_intel block. `competitor_sample` is analysis-only (never read by the
    generation/SEO stages) so competitor text cannot leak into product content."""
    from .models import now
    with connect() as conn:
        conn.execute(
            """INSERT INTO competitive_intel
               (trend_id, saturation, gap_analysis, seo_pattern, competitor_sample, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(trend_id) DO UPDATE SET
                 saturation=excluded.saturation, gap_analysis=excluded.gap_analysis,
                 seo_pattern=excluded.seo_pattern, competitor_sample=excluded.competitor_sample,
                 created_at=excluded.created_at""",
            (trend_id,
             json.dumps(block.get("saturation") or {}, ensure_ascii=False),
             json.dumps(block.get("gap_analysis") or [], ensure_ascii=False),
             json.dumps(block.get("seo_pattern") or {}, ensure_ascii=False),
             json.dumps(block.get("competitor_sample") or {}, ensure_ascii=False),
             now()),
        )


def get_competitive_intel(trend_id: int) -> dict | None:
    """Read a trend's competitive-intel block back (saturation/gap_analysis/seo_pattern only —
    competitor_sample is intentionally omitted from the pipeline-facing view)."""
    with connect() as conn:
        r = conn.execute(
            "SELECT saturation, gap_analysis, seo_pattern FROM competitive_intel WHERE trend_id=?",
            (trend_id,),
        ).fetchone()
    if not r:
        return None
    return {"saturation": json.loads(r["saturation"] or "{}"),
            "gap_analysis": json.loads(r["gap_analysis"] or "[]"),
            "seo_pattern": json.loads(r["seo_pattern"] or "{}")}


# --- Run log (post-hoc failure visibility) ---

def log_run(stage: str, status: str, detail: str = "") -> None:
    """Append one run-log row (stage, status, timestamp) so a run's outcome is visible after the fact.

    Best-effort by design: observability must never break the pipeline, so a logging failure is
    swallowed rather than raised into the caller."""
    from .models import now
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO run_log (stage, status, detail, created_at) VALUES (?,?,?,?)",
                (stage, status, detail, now()),
            )
    except Exception:
        pass


def run_log(limit: int = 100) -> list[dict]:
    """Most recent run-log rows first (stage, status, detail, created_at)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, stage, status, detail, created_at FROM run_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# --- Listing keywords (target keywords for rank tracking) ---

def upsert_listing_keyword(product_id: int, etsy_listing_id: int, keyword: str,
                           is_primary: bool = True) -> None:
    from .models import now
    ts = now()
    with connect() as conn:
        # If setting as primary, demote any other primary keyword for this listing.
        if is_primary:
            conn.execute(
                "UPDATE listing_keywords SET is_primary=0, updated_at=? "
                "WHERE etsy_listing_id=? AND is_primary=1",
                (ts, etsy_listing_id),
            )
        conn.execute(
            """INSERT INTO listing_keywords
               (product_id, etsy_listing_id, keyword, is_primary, created_at, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(product_id, etsy_listing_id, keyword) DO UPDATE SET
                 is_primary=excluded.is_primary, updated_at=excluded.updated_at""",
            (product_id, etsy_listing_id, keyword, 1 if is_primary else 0, ts, ts),
        )


def listing_keywords_for(product_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM listing_keywords WHERE product_id=? ORDER BY is_primary DESC, id",
            (product_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def primary_keyword_for(etsy_listing_id: int) -> str | None:
    with connect() as conn:
        r = conn.execute(
            "SELECT keyword FROM listing_keywords WHERE etsy_listing_id=? AND is_primary=1",
            (etsy_listing_id,),
        ).fetchone()
    return r["keyword"] if r else None


def all_listing_keywords() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT lk.*, p.bundle_type, el.product_id
               FROM listing_keywords lk
               JOIN etsy_listings el ON el.etsy_listing_id = lk.etsy_listing_id
               JOIN products p ON p.id = el.product_id
               ORDER BY lk.id"""
        ).fetchall()
    return [dict(r) for r in rows]


def delete_mockups_not_in(product_id: int, kinds: list[str]) -> int:
    """Purge stale mockup rows whose kind isn't in the current set. When a
    product's item set changes (single print -> 3-print set), the old kind
    list can differ; stale rows otherwise get re-uploaded to Etsy (#122's
    old size_guide bug)."""
    with connect() as conn:
        placeholders = ",".join("?" * len(kinds))
        cur = conn.execute(
            f"DELETE FROM mockups WHERE product_id=? AND kind NOT IN ({placeholders})",
            (product_id, *kinds))
    return cur.rowcount


# --- Keyword pulse (true current-velocity time series) ---

def insert_pulse_rows(keyword: str, rows: list[tuple[int, int, int]]) -> None:
    """rows: [(listing_id, views, favorites)] captured now."""
    from .models import now
    ts = now()
    with connect() as conn:
        conn.executemany(
            """INSERT INTO keyword_pulse (keyword, listing_id, views, favorites,
               captured_at) VALUES (?,?,?,?,?)""",
            [(keyword, lid, v, f, ts) for lid, v, f in rows],
        )


def pulse_snapshots(keyword: str, last_n_captures: int = 2) -> list[list[dict]]:
    """The last N capture batches for a keyword, oldest first. Each batch is
    the list of per-listing rows sharing one captured_at."""
    with connect() as conn:
        times = [r["captured_at"] for r in conn.execute(
            """SELECT DISTINCT captured_at FROM keyword_pulse WHERE keyword=?
               ORDER BY captured_at DESC LIMIT ?""", (keyword, last_n_captures))]
        batches = []
        for t in reversed(times):
            rows = conn.execute(
                "SELECT * FROM keyword_pulse WHERE keyword=? AND captured_at=?",
                (keyword, t)).fetchall()
            batches.append([dict(r) for r in rows])
    return batches


def pulse_keywords() -> list[str]:
    with connect() as conn:
        return [r["keyword"] for r in conn.execute(
            "SELECT DISTINCT keyword FROM keyword_pulse ORDER BY keyword")]


# --- Rank snapshots ---

def insert_rank_snapshot(etsy_listing_id: int, keyword: str, rank: int | None,
                         total_results: int, result_count: int, page: int,
                         found: bool) -> None:
    from .models import now
    with connect() as conn:
        conn.execute(
            """INSERT INTO rank_snapshots
               (etsy_listing_id, keyword, rank, total_results, result_count, page, found, pulled_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (etsy_listing_id, keyword, rank, total_results, result_count, page,
             1 if found else 0, now()),
        )


def latest_rank_snapshot(etsy_listing_id: int, keyword: str) -> dict | None:
    with connect() as conn:
        r = conn.execute(
            """SELECT * FROM rank_snapshots
               WHERE etsy_listing_id=? AND keyword=?
               ORDER BY pulled_at DESC LIMIT 1""",
            (etsy_listing_id, keyword),
        ).fetchone()
    return dict(r) if r else None


def previous_rank_snapshot(etsy_listing_id: int, keyword: str) -> dict | None:
    """Second-most-recent snapshot, for trend arrows."""
    with connect() as conn:
        r = conn.execute(
            """SELECT * FROM rank_snapshots
               WHERE etsy_listing_id=? AND keyword=?
               ORDER BY pulled_at DESC LIMIT 1 OFFSET 1""",
            (etsy_listing_id, keyword),
        ).fetchone()
    return dict(r) if r else None


def latest_ranks() -> list[dict]:
    """Most recent rank snapshot per listing/keyword, joined to product + listing."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT rs.*, el.product_id, p.bundle_type, l.title AS listing_title
               FROM rank_snapshots rs
               JOIN (SELECT etsy_listing_id, keyword, MAX(pulled_at) AS mx
                     FROM rank_snapshots GROUP BY etsy_listing_id, keyword) last
                 ON last.etsy_listing_id = rs.etsy_listing_id
                 AND last.keyword = rs.keyword
                 AND last.mx = rs.pulled_at
               JOIN etsy_listings el ON el.etsy_listing_id = rs.etsy_listing_id
               JOIN products p ON p.id = el.product_id
               LEFT JOIN listings l ON l.product_id = el.product_id
               ORDER BY rs.rank IS NULL, rs.rank DESC, rs.total_results DESC"""
        ).fetchall()
    return [dict(r) for r in rows]
