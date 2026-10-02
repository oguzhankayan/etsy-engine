# Current Pipeline — Operator and Agent Guide

This is the canonical description of the pipeline that is implemented in code.
If another document disagrees with this file, verify `src/etsy_engine/pipeline.py`
and update the stale document before operating the shop.

## 1. Read before running

1. Never reset `data/engine.db` or delete `data/product_history.jsonl`.
2. If listings may have been created on another machine, run:

   ```bash
   .venv/bin/python scripts/sync_etsy_history.py
   ```

3. Inspect the queue before generation. `generate`, `mockups`, and `seo` process
   every product in their matching status, not only products created by the most
   recent command.
4. Publishing creates an Etsy draft only. A human must review it, select
   “With an AI generator” in Etsy, and publish manually.

## 2. Implemented data flow

```text
ideas + Google + Reddit + Etsy-suggest
                 │
                 ▼
collect → score → validate → architect → generate → mockups → seo → publish
   │         │         │           │           │          │       │       │
 SQLite   Claude   Etsy market   product     pages +    listing  copy   DRAFT
 trends   prior    evidence      format      vision QC  images
                 
publish → metrics → learn → product-idea performance + scoring weights
        → rank-track → optimize → optimize-apply
```

The engine is Etsy-demand-first. Google is a weak radar for momentum; it is not
the primary proof that buyers will purchase a product.

## 3. Discovery and self-improving product ideas

`collect` uses all registered sources by default:

- `ideas`: rotating product-format and theme combinations from the tracked
  `src/etsy_engine/product_ideas_catalog.json` plus the learned local layer in
  `data/product_ideas.json`;
- `google`: daily RSS trends plus a rotating seed allocation across product ideas,
  seasonal terms, evergreen terms, and learned winners;
- `velocity`: our own Etsy bestseller radar (`sources/etsy_velocity.py`). Samples
  the top active listings per digital category and ranks them by demand velocity
  (favorites/day, views/day) from the public `/listings/active` fields, surfacing
  the fastest risers as clean theme seeds. Honest limit: Etsy's public API exposes
  views + favorites, not competitors' sales, so velocity is a purchase-intent proxy.
  The velocity is carried in `raw_payload` and floors virality in `score`.
- `reddit`: problem/community signals when credentials are available;
- `etsy`: currently fails soft because the old autosuggest endpoint returns 403.

Discovery seeds also include a curated **Pinterest Predicts** pool
(`sources/seeds.py::PINTEREST_PREDICTS_2026`) — the annual "not-yet-trending"
forecast, hand-mapped to Etsy search phrases (Etsy buyers ≈ Pinterest users).
It is an early cross-platform trend signal; refresh once a year when the new
report drops. Each seed still passes through Google/velocity + Etsy market
validation before anything is produced.

The idea catalog includes questionnaires, coupon books, party games, greeting
cards, coloring books, wall art, banners, planner kits, checklist/trackers, and
sticker sheets. Concrete theme × format combinations are generated automatically.
Previously produced themes are filtered with per-product similarity, not a global
ban on generic words such as `tracker` or `kids`.

## 4. Stages and exact behavior

### collect

```bash
.venv/bin/etsy-engine collect
# or explicitly:
.venv/bin/etsy-engine collect --sources ideas,google,reddit
```

Fetches candidates, applies the cheapest IP blocklist, and upserts trends into
SQLite. Network sources fail soft. Google 429 responses can reduce coverage while
the `ideas` source continues to work.

### score

```bash
.venv/bin/etsy-engine score
```

Claude Sonnet 5 scores only unscored trends for virality, purchase intent,
productization, competition, longevity, and IP risk. This is a prior, not final
market proof.

### validate

```bash
.venv/bin/etsy-engine validate --top-k 35
```

Calls Etsy market intelligence for leading candidates and persists competition,
demand proxy, beatability, price, top tags, and an adjusted score. Current code
uses 40% LLM composite, 30% Etsy demand score, and 30% beatability. True Etsy
search volume is unavailable, so `avg_daily_views` is evidence from ranked
listings, not search-volume data.

Do not skip this stage. Architect prefers validated candidates and falls back to
LLM-only candidates only when no validated candidates exist.

### architect

```bash
.venv/bin/etsy-engine architect -n 3
```

Filters durable history and existing product trend ids, then applies bounded
archetype diversity. Real Etsy titles/tags inform the structure without being
copied. Product-idea triggers can override the binary Etsy delivery route so a
coloring book, questionnaire, banner, or tracker remains the correct format.

Output status: `planned`. No images or Etsy listings are created.

### generate

```bash
.venv/bin/etsy-engine report
.venv/bin/etsy-engine generate --variations 2
```

Generates every `planned` product. Each item gets Raywake (GPT Image 2.5) variations and
Claude vision QC; the best image is stored. Missing items receive a self-heal
retry. Status becomes `qc_passed` or `generated`.

Important: inspect all planned rows first. This command is queue-wide.

### mockups

```bash
.venv/bin/etsy-engine mockups
```

Processes every `generated`/`qc_passed` product. Real product pages are used as
references so listing images remain faithful. Bundles receive six mockups;
single-item products receive three. Status becomes `mockups_done`.

### seo

```bash
.venv/bin/etsy-engine seo
```

Processes every `mockups_done` product. Produces title, 13 tags, description,
alt text, FAQ, and the AI disclosure. Status becomes `seo_done`.

### publish

```bash
.venv/bin/etsy-engine publish --product-id <id>
```

Creates an Etsy draft, uploads ordered mockups and digital files, stores the
primary rank keyword, writes `PRODUCT_REPORT.md`, and appends durable history.
It never activates the listing. `when_made` is `2020_2026` and listing type is
`download`.

### shop profile

```bash
.venv/bin/etsy-engine etsy-shop-profile          # preview
.venv/bin/etsy-engine etsy-shop-profile --apply  # update title + buyer messages
```

The canonical profile copy is in `publish/shop_profile.py`. Applying it requires
OAuth scope `shops_w`; re-run `etsy-engine etsy-auth` after adding that scope.
Etsy's Open API does not expose shop-banner uploads; set the banner in Shop Manager.

## 5. Recommended operating workflows

### Safe staged workflow

Use this when reviewing opportunities before spending image credits:

```bash
.venv/bin/python scripts/sync_etsy_history.py
.venv/bin/etsy-engine collect --sources ideas,google,reddit
.venv/bin/etsy-engine score
.venv/bin/etsy-engine validate --top-k 35
.venv/bin/etsy-engine report
.venv/bin/etsy-engine architect -n 3
.venv/bin/etsy-engine report
# Confirm every planned product, then:
.venv/bin/etsy-engine generate --variations 2
.venv/bin/etsy-engine mockups
.venv/bin/etsy-engine seo
.venv/bin/etsy-engine report
.venv/bin/etsy-engine publish --product-id <id>
```

### Automated pre-publish workflow

```bash
.venv/bin/etsy-engine run --full
```

Runs `collect → score → validate → architect → generate → mockups → seo` and stops
before Etsy publish. Because generation stages are queue-wide, use this only after
checking that no unintended `planned` products are waiting.

### Full one-command production

```bash
.venv/bin/etsy-engine produce -n 3
```

Selects from already scored/validated opportunities, alternates evergreen and
viral lanes, generates everything, and creates Etsy drafts. It does not first run
fresh `collect/score/validate`. Use the staged workflow first when fresh market
data matters.

## 6. Product lifecycle

```text
planned
  → generated | qc_passed
  → mockups_done
  → seo_done
  → drafted
  → published (after external/manual confirmation)
```

`deleted` is used operationally for abandoned local rows and must not re-enter
generation.

### Listing keep-alive (never delete seasonal work)

Seasonal listings accrue search/sales history all year; deleting one forces next
season to start from zero. Publishing now tags seasonal listings (`is_seasonal`,
`season` on `etsy_listings`) and defaults `should_auto_renew=True` for evergreen +
seasonal products (only a genuine one-off viral moment is left to lapse).

```bash
.venv/bin/etsy-engine renew --report   # list listings + seasonal keep-alive flags
.venv/bin/etsy-engine renew --dry-run  # preview what would be kept alive
.venv/bin/etsy-engine renew            # PATCH should_auto_renew on Etsy
```

`renew` backfills seasonal tags from existing SEO titles, so the current live
inventory is protected too. A listing with ≥20 views, ≥2 favorites, or ≥1 sale is
also treated as proven and kept alive even if it began as a one-off viral bet.
`publisher.delete_listing` refuses to remove a seasonal listing without
`force=True`.

### Q4 front-loading

`sources/seeds.py` widens the Halloween/Thanksgiving/Christmas prep windows into
late summer, and `product_ideas.seasonal_boost` tilts selection toward products
whose season peaks within ~2 months. `scripts/q4_sprint.py` runs the normal funnel
with a Q4 emphasis (dry preview by default; `--run` produces drafts).

## 7. Learning and optimization

```bash
.venv/bin/etsy-engine metrics
.venv/bin/etsy-engine learn
.venv/bin/etsy-engine rank-track
.venv/bin/etsy-engine rank-report
.venv/bin/etsy-engine optimize --dry-run
.venv/bin/etsy-engine optimize-apply --product-id <id>
```

`metrics` snapshots Etsy performance. `learn` updates scoring weights and
idempotently synchronizes performance to rich product archetypes. Market winners
can become learned seeds. `metrics` also maps real Etsy lifecycle state back to
the product queue (`active → published`, `edit/draft → drafted`) so live listings
cannot accidentally re-enter mockup or SEO generation. Rank tracking and
optimization improve existing listings without creating new products.

## 8. Current limitations

- No true Etsy search volume or keyword difficulty data. The `velocity` source is
  the closest proxy (favorites/views velocity on live listings), not literal sales.
- Etsy autosuggest currently returns 403.
- Cross-language duplicate normalization is incomplete.
- Live-shop history sync is manual.
- Pinterest/Postiz is not an automatic pipeline stage.
- The Etsy AI-generator radio and final publish are manual UI actions.
