"""Domain models for the pipeline. Plain dataclasses kept close to the DB schema."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import IntEnum


def now() -> str:
    return datetime.now(UTC).isoformat()


class Tier(IntEnum):
    VIRAL = 1  # 1-14 days
    SEASONAL = 2  # 1-3 months
    EVERGREEN = 3  # years


# Product lifecycle — the backbone of the pipeline.
STATUSES = [
    "planned",
    "designed",
    "generated",
    "qc_passed",
    "mockups_done",
    "seo_done",
    "drafted",
    "published",
]


@dataclass
class Trend:
    source: str
    term: str
    raw_payload: str = ""  # JSON string of source-specific data
    tier: Tier = Tier.VIRAL
    discovered_at: str = field(default_factory=now)
    id: int | None = None


@dataclass
class Score:
    trend_id: int
    virality: float
    purchase_intent: float
    productization: float
    competition: float  # higher = less crowded
    longevity: float
    ip_risk: float  # 0 = safe, 1 = certain infringement
    composite: float
    rationale: str = ""
    scored_at: str = field(default_factory=now)
    id: int | None = None


@dataclass
class BundleItem:
    product_id: int
    name: str
    asset_type: str  # poster, worksheet, tracker, certificate, ...
    spec: str = ""  # free-text spec for the Prompt Builder
    id: int | None = None


@dataclass
class Product:
    trend_id: int
    title_concept: str
    bundle_type: str  # e.g. "Family Camping Planner Bundle"
    status: str = "planned"
    format: str = "pdf"  # 'pdf' (print-at-home bundle) | 'canva' (editable Canva suite)
    created_at: str = field(default_factory=now)
    id: int | None = None


@dataclass
class DesignSystem:
    """Art Director output (Agent 5) — the visual language for a whole bundle."""
    product_id: int
    palette: str  # JSON list of hex colors
    style_notes: str
    icon_style: str
    aesthetic: str
    typography: str = ""
    id: int | None = None


@dataclass
class Asset:
    """A generated page/image for one bundle item (Agent 7 output)."""
    bundle_item_id: int
    prompt: str
    file_path: str
    qc_status: str = "pending"  # pending | passed | failed | skipped
    qc_score: float = 0.0
    qc_notes: str = ""
    variations: int = 1  # how many were generated before picking this one
    created_at: str = field(default_factory=now)
    id: int | None = None


# Etsy listing-image set the Mockup Generator produces (Agent 9).
MOCKUP_KINDS = [
    "hero", "lifestyle", "contents_overview",
    "close_up", "feature_highlight", "size_guide",
]


@dataclass
class Mockup:
    product_id: int
    kind: str  # one of MOCKUP_KINDS
    prompt: str
    file_path: str
    created_at: str = field(default_factory=now)
    id: int | None = None


@dataclass
class Listing:
    """SEO Writer output (Agent 10) — the Etsy listing copy."""
    product_id: int
    title: str  # <= 140 chars
    tags: str  # JSON list of <=13 tags, each <=20 chars
    description: str
    alt_texts: str = "[]"  # JSON list, one per mockup
    faq: str = ""
    created_at: str = field(default_factory=now)
    id: int | None = None
