"""Central configuration. Reads .env via pydantic-settings.

Keys are optional at import time so the package can be inspected without
credentials; each component checks for the keys it actually needs and raises a
clear error if missing.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = three levels up from this file (src/etsy_engine/config.py)
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"


class ScoringWeights(BaseSettings):
    """Weights for the 6-factor opportunity rubric. Faz 5 tunes these."""

    virality: float = 0.20
    purchase_intent: float = 0.30  # what people actually pay for matters most
    productization: float = 0.20
    competition: float = 0.15  # higher score = LESS crowded (good)
    longevity: float = 0.15
    # ip_risk is not a weight: it's a hard gate, handled in ip_filter.


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM — one Sonnet-class model for everything (text AND vision QC). Opus is ~5x the
    # cost for no measurable gain on this workload.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    anthropic_vision_model: str = "claude-sonnet-5"

    # Image generation — Raywake (https://raywake.com). Create a key under API keys in
    # the studio with the `generate` and `jobs:read` scopes. See generate/raywake.py.
    raywake_api_key: str = ""
    raywake_base_url: str = "https://api.raywake.com"
    raywake_model: str = "openai/gpt-image-2.5/sunburst/text-to-image"
    raywake_edit_model: str = "openai/gpt-image-2.5/sunburst/edit"   # reference-faithful mockups
    raywake_quality: str = "high"   # low | medium | high | xhigh | max (higher = more credits)

    # Your storefront identity — printed in buyer-facing delivery PDFs and shop copy.
    shop_name: str = "Your Shop"
    shop_contact_email: str = ""

    # OpenRouter — powers the X (Twitter) trend source via Grok's native x_search (sources/x_trends).
    # OpenAI-SDK-compatible endpoint; key lives in .env (never committed). Additive Line-A source.
    openrouter_api_key: str = ""
    # grok-4.1-fast is deprecated on OpenRouter (404 -> "switch to Grok 4.3"); 4.3 is the current
    # Grok 4+ model, so native web/x search (x_search) still applies. Override via OPENROUTER_MODEL.
    openrouter_model: str = "x-ai/grok-4.3"

    # context.dev competitive-intelligence enrichment (stage 03 VALIDATE). Runs only when a key is
    # set, enriching high-scoring candidates during validate.
    # It measures Etsy market SATURATION and surfaces buyer GAPS (never copies competitor content).
    # Set context_dev_enabled=False (or unset the key) to go dark. Key lives in .env.
    context_dev_api_key: str = ""
    context_dev_enabled: bool = True             # no-op without CONTEXT_DEV_API_KEY
    context_dev_extract_cap: int = 5             # max web.extract (~10cr) calls per validate run
    context_dev_max_enrich: int = 8              # max CANDIDATES enriched per run (bounds web.search too)
    context_dev_cache_ttl_hours: float = 168.0   # don't re-extract the same URL within this window
    context_dev_enrich_min_score: float = 0.6    # only enrich candidates that cleared stage 02 above this
    context_dev_results_per_search: int = 3      # top listing pages to web.extract per candidate

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "etsy-trend-engine/0.1"

    # Etsy
    etsy_api_key: str = ""
    etsy_shared_secret: str = ""
    etsy_shop_id: str = ""
    etsy_oauth_token: str = ""
    etsy_oauth_refresh_token: str = ""
    etsy_redirect_uri: str = "http://localhost:3003/oauth/callback"
    etsy_scopes: str = (
        "listings_r listings_w listings_d shops_r shops_w transactions_r"
    )
    etsy_taxonomy_id: int = 0  # planner-kit default; set via `etsy-engine etsy-taxonomy`
    etsy_taxonomy_id_print: int = 2078  # Art & Collectibles > Prints > Digital Prints
    etsy_default_price: float = 5.0
    # Prints clamp to the niche median (computed in market_intel). Band widened
    # 2026-07-01 after a price audit: digital wall-art medians are ~$6-8 (p75 ~$10-12),
    # so the old $5 max pinned every print to the market FLOOR. $4-10 lets prints
    # track the median without going out of market.
    print_price_min: float = 4.0
    print_price_max: float = 10.0
    # Bundles (planner/coloring/party/…) track the niche median clamped to this
    # band. Floor = the old flat default (never cheaper); ceiling lets substantial
    # bundles (e.g. 20-page coloring books, niche median ~$7, p75 ~$14) price up.
    bundle_price_min: float = 5.0
    bundle_price_max: float = 9.99
    etsy_currency: str = "USD"

    # Postiz / Pinterest (Postiz subscription ended — kept for reference)
    postiz_base_url: str = "https://api.postiz.com"
    postiz_api_key: str = ""
    pinterest_postiz_integration_id: str = ""
    # Direct Pinterest API v5 (replaces Postiz; see marketing/pinterest.py).
    # Create an app at developers.pinterest.com/apps and fill these:
    pinterest_app_id: str = ""
    pinterest_app_secret: str = ""
    pinterest_redirect_uri: str = "http://localhost:8085/callback"
    pinterest_board_id: str = ""  # default board for pin-queue
    # Until the Pinterest app gets Trial/Standard access approval, tokens only
    # work against the sandbox host — set this in .env accordingly. Sandbox
    # pins do NOT appear on real Pinterest; swap back once approved.
    pinterest_api_base: str = "https://api.pinterest.com/v5"

    # Trend geos for the Google daily RSS feed (comma list of 2-letter codes).
    # This general trending feed is the PRIMARY intake channel (seeds are a
    # supplementary evergreen layer). Broad geo coverage = catch global trends.
    # Rising queries stay single-geo to avoid pytrends rate limits.
    trend_geos: str = "US,GB,CA,AU,IN,BR,DE,FR"

    # Funnel
    funnel_inspect: int = 100
    funnel_filter: int = 20
    funnel_opportunities: int = 10
    funnel_products: int = 3
    # Canva PRODUCTION QUOTA: reserve at least this many of the `funnel_products` slots per run for the
    # top-ranked Canva-suitable candidate(s). Editable markets (weddings, invitations, funeral programs)
    # are huge but SATURATED, so the winnability-weighted score buries them below niche PDF trends and
    # the Canva line would starve. 0 disables the reservation (pure rank order).
    canva_min_per_run: int = 1

    # Expected-value gate (cost circuit-breaker before stage 05 / image generation). A planned
    # product whose projected monthly $ profit (scoring.ev_gate) is below this floor is blocked and
    # never spends image credits. Default 0.0 = permissive: block only projected-LOSS products; raise
    # it (e.g. 5.0) to build more selectively. Env: EV_GATE_MIN.
    ev_gate_min: float = 0.0

    # Catalog cap: refuse to create a NEW Etsy draft once the shop already has >= this many ACTIVE
    # listings (publish.enforce_catalog_cap). Guards the over-built catalog — the profitability
    # audit's #1 leak (13x demand): every dead listing costs renewal fees and dilutes the shop.
    # Default 0 = disabled (opt-in; behavior unchanged until set). Env: CATALOG_ACTIVE_CAP.
    catalog_active_cap: int = 0

    db_path: Path = Field(default=DATA_DIR / "engine.db")

    def require(self, *names: str) -> None:
        """Raise a clear error if any named setting is empty."""
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError(
                "Missing required config: "
                + ", ".join(missing)
                + ". Add them to your .env (see .env.example)."
            )


settings = Settings()
weights = ScoringWeights()

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Learned scoring weights are persisted here by the Faz 5 feedback loop.
WEIGHTS_FILE = DATA_DIR / "weights.json"


def current_weights() -> ScoringWeights:
    """Default weights, overridden by anything the learning loop has saved."""
    if WEIGHTS_FILE.exists():
        import json
        try:
            return ScoringWeights(**json.loads(WEIGHTS_FILE.read_text()))
        except Exception:
            pass
    return ScoringWeights()


def save_weights(w: ScoringWeights) -> None:
    import json
    WEIGHTS_FILE.write_text(json.dumps(w.model_dump(), indent=2))
