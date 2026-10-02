# RULES — how to operate this project (read before doing anything)

If you are an agent taking over, follow these rules so you work like the previous
operator: Etsy-demand-first, data-validated, honest, and non-destructive. Read this top
to bottom, then [docs/PIPELINE.md](docs/PIPELINE.md) for the implemented workflow and
[docs/SETUP.md](docs/SETUP.md) for setup and Etsy-specific mechanics.

---

## A. Working philosophy (how to think)

1. **Etsy-DEMAND-first.**
   The PRIMARY signal is real **Etsy** buyer demand + winnability, computed from the
   Etsy API (`scoring/etsy_market.market_intel`): real views/daily-views (demand),
   listing age + competition (winnability/beatability), dominant category (format),
   median price, real top tags. Google Trends is only a weak first-mover RADAR for
   genuinely productizable spikes; most of it is news/tragedy noise. eRank is a
   optional MANUAL oracle you can feed occasionally (search VOLUME + KD only — no API, never
   automated). The LLM 6-factor score is now a prior/tie-breaker, not the driver.
   Don't get stuck in a few niches.
2. **Read ANY trend, then design the product that FITS it.** A trend can be an
   aesthetic, a hobby, a season, a meme, a cultural/entertainment moment, an
   event. Find the printable/digital product that rides it. Do NOT over-fit to one
   category (e.g. don't make everything "sports" or everything "planner"). Think
   like an Etsy buyer: "what would a fan of THIS trend actually buy?"
3. **Validate with real data before producing.** Cross-check every candidate trend
   against real Etsy market data (competition = listing count, demand = top-listing
   favorites). Make the matches — trends that are rising AND have proven Etsy
   demand AND aren't hopelessly saturated.
4. **Match the ARCHETYPE to what the niche actually buys** (updated 2026-06-08).
   `market_intel` picks the format per trend — do NOT force everything into one mold:
   - **planner / kit** — a SYSTEM of 6–10 cohesive pages (when the niche buys kits);
   - **wall-art print** — ONE striking decorative design (when the niche buys prints/
     PNG/wall art, e.g. World Cup, where Digital Prints dominate);
   - **party / invitation** printables where that's the intent.
   Sell what that niche's top sellers sell, not a kit by reflex.
5. **Learn from competitors, never copy them.** Read top-seller TITLES to learn
   structure/components/positioning; generate 100% original artwork and wording.
6. **Minimal in clutter, NOT in character.** Clean layouts with white space — but
   keep the warm, playful, joyful soul. Never make it sterile/corporate.
7. **Be honest.** Report decisions, archive provenance, never fake data, never
   silently substitute one source for another. Surface limitations.

## A2. Two production lanes — ALWAYS ALTERNATE

Production runs **two lanes** and alternates between them:
- **EVERGREEN** — Etsy-validated, proven-demand opportunities (ranked by adjusted_score).
- **VIRAL** — high-momentum trending events, first-mover bets (ranked by virality);
  NOT gated on existing Etsy history (the point is it's new). Prefer the daily
  general feed; ride trademarked moments only via their GENERIC angle (tennis, not
  "Roland Garros"; soccer, not "World Cup™").

Rule: `etsy-engine produce -n N` makes N products **alternating lanes**, starting
the OPPOSITE of the last product's lane (persisted in `data/last_lane.txt`). So
`produce -n 1` does the opposite of the last one; `produce -n 6` → 3 evergreen +
3 viral. Both lanes dedup against the durable history. Reality check: usable viral
plays are scarce/IP-constrained on any given day — that's expected, not a bug.

## B. Hard operating rules (never break)

1. **NEVER reset `data/engine.db`.** Product ids and `output/<id>/` folders
   accumulate as the permanent archive. (A past reset lost the first product
   locally — don't repeat it.)
2. **NEVER delete `data/product_history.jsonl`.** It's the append-only, durable
   product history that survives DB resets and is the source of truth for
   duplicate prevention.
3. **Always dedup before producing.** Use `history.is_duplicate()` plus current DB
   product trend ids. Do not restore the old global-token intersection: generic
   words such as `tracker`, `kids`, or `activity` must not block unrelated ideas.
4. **Drafts only.** Listings are created as drafts; a human reviews and publishes.
   Never auto-activate a listing.
5. **Archive provenance.** Every product gets `output/<id>/PRODUCT_REPORT.md`
   (auto at publish) and a `product_history.jsonl` line.
6. **Don't commit secrets.** `.env`, `data/`, `output/` are gitignored.
7. **Never delete seasonal or proven listings; keep them alive year-round.** A seasonal
   listing accrues a year of search/sales history — deleting it forces next season
   to start from zero. Publishing tags seasonal listings and defaults them to
   auto-renew; `renew` also protects any listing that reaches 20 views, 2 favorites,
   or 1 sale. Run `etsy-engine renew` periodically (and before Q4). `delete_listing`
   refuses to remove a seasonal listing without `force=True`. Prep Q4 early so
   listings gather history before the peak.

## C. Etsy specifics (the gotchas that cost hours)

1. **`x-api-key` header must be `keystring:shared_secret`** (since 2026-02-09).
   Just the keystring → 403 "Shared secret is required in x-api-key header".
2. **`when_made` must be `2020_2026`, NOT `made_to_order`** — otherwise the listing
   shows "Made to order" instead of an instant digital download. (Files
   bundle.pdf + individual-pages.zip are attached; type=download.)
3. **The "With an AI generator" radio is NOT in the API** — a human must tick it
   in the Etsy UI per listing before publishing. We auto-add only the description
   disclosure (required by Etsy's AI policy).
4. **Title rule:** `&` only once (later → "and"); keep titles short/clear/
   front-loaded (position doesn't affect ranking; it's for human clarity).
5. **Digital files cap at 5** → ship exactly two: `bundle.pdf` (all pages) +
   `individual-pages.zip` (each page).
6. **Attributes matter** (color/occasion) — they act like tags and power filters;
   set them (auto in publish).
7. **Taxonomy id required** to create a listing (current: 354 Calendars & Planners;
   adjust per product type via `etsy-engine etsy-taxonomy "<query>"`).

## D. Quality bar

- Printables: text rendered directly by the image model (GPT Image 2.5 via Raywake), 1536x2048,
  QC ≥ 0.7 (generate-many / pick-best). Mockups: 2048x2048, 6 per product.
- SEO: research-driven, 13 long-tail diverse tags, 160-char-hook description,
  per-image alt text, FAQ, + AI disclosure appended.

## E. Communication

- Keep all code, comments, and docs in English.
- When something is hard/uncertain, say so plainly and propose options.

## F. Models & cost (watch this — money lives here)

- **ALL LLM calls use one Sonnet-class model** (config: `anthropic_model` AND
  `anthropic_vision_model`, mirrored in `.env`). **Not Opus** — an Opus default once
  cost ~$5–6 of LLM for just 12 products. Not Haiku either: QC quality drops.
- **Cost driver = QC vision**: ~1 vision call per generated page → ~10 per product.
  That volume is why the model choice matters so much. If asked to cut LLM cost
  further, reduce QC calls (e.g. sample pages), don't downgrade quality silently.
- **Check your Raywake balance before big runs** (`etsy-engine credits`). Every image
  is quoted before it starts, and **mockups dominate** (large reference-faithful edits
  cost more than a page). Prefer `--variations 1` when the balance is low, and never
  start a bundle you can't finish — a mid-run credit-out leaves a half-generated,
  unpublishable product.

## G. Performance & robustness (already built in — keep it)

- **Parallel generation:** assets + mockups are generated CONCURRENTLY
  (`ThreadPoolExecutor`, ~8 workers; DB writes stay in the main thread). ~12
  products take ~30–40 min, not hours. Don't make it sequential again.
- **No missing pages, ever:** the Raywake client retries transient failures (timeout/429/5xx) idempotently;
  `generate_product` self-heals any item left without an asset; `produce_one`
  REFUSES to publish if `assets < bundle items`. A bundle has 6–10 items (the
  architect chooses), so "complete" means `assets == items == pdf pages`, not a
  fixed 10.
- **Published deliverables live ON ETSY** (files attached to the listing). Local
  `output/<id>/` is just a working copy — losing it never breaks fulfillment of an
  already-published listing.

## H. Banners (the one sanctioned cut-out form)

> Source of truth is CODE, not this doc. Nothing here is read at runtime — the
> behavior lives in `product/architect.py` + `generate/banner.py`. This section
> is the human summary; change the code to change the rule.

**Free-form / AI-drawn banners, garlands, and bunting stay BANNED** (they shipped
as unusable flat "infographic" pages — the #113/#118/#11 lesson). The ONE exception
is a **deterministic letter banner**, and only under these rules:

1. **When allowed:** only in a DECOR context — classroom, party, birthday, baby
   shower, nursery, holiday decor (see `DECOR_TERMS` / `_is_decor_context`). Never
   in a non-decor product.
2. **How many:** at most **ONE** `letter_banner` component per bundle (it expands
   to a whole print-and-cut set on its own). Extras are dropped.
3. **How it's built:** NOT by the AI image model. `generate/banner.py` makes one
   themed blank pennant (a single image call from the product's design system,
   cached at `output/<pid>/_pennant.png`), then **stamps** each letter/word onto a
   copy with the bundled serif (`assets/fonts/Gelasio.ttf`) in the theme's ink
   color. Result: every flag identical except its glyph, spelling always correct,
   **one usable pennant per A4 page @ 300 dpi**, no titles/marketing.
4. **How it's specified:** the component's `spec` embeds a JSON directive the
   compositor parses:
   `{"banner":{"segments":[{"kind":"word","text":"WELCOME"},{"kind":"alphabet","numbers":true},{"kind":"months"}]}}`
   — kinds: `word`, `alphabet` (opt. `numbers`), `months`, `words` (list), `blanks`
   (count). The banner item is stored as a multi-page **PDF** asset.
5. **Copy honesty:** because a real banner now ships, `seo/writer.py` allows the
   words "banner"/"pennant" in tags/title **only when the bundle has a
   `letter_banner`** — otherwise they're still stripped as a promise-mismatch.
