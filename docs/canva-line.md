# Canva-editable product line (ADDITIVE)

> The primary print-at-home **PDF pipeline does not change.** This is a separate,
> parallel line with its own images, mockups, delivery and copy. `pipeline.py` /
> `publish/publisher.py` / `seo/writer.py` and every PDF product behave exactly as before.
> **Proven end-to-end** on a live Etsy draft.

## Why

In our best niches (host/guest, classroom, wedding) the champions are **Canva-editable**
templates ($8–12); we shipped non-editable PDF. This line closes that format gap and is
priced into that tier honestly.

## The approach (v3): image model → Canva Magic Layers → i2i mockups → Etsy draft

The lesson from earlier: do NOT ask an LLM to lay out an editable multi-field template
(human craft; it reads amateur). Instead:

1. **The image model renders the WHOLE finished design** per page (composition, type, icons)
   — where AI genuinely excels.
2. **Canva Magic Layers** (the seller's manual step) turns each flat page into editable layers.
3. **i2i mockups** (Raywake GPT Image 2.5 edit) drop the real designs into premium scenes.

## ⛔ Agent runbook — human-in-the-loop (READ THIS FIRST)

Canva production has **three actors and a mandatory WAIT**. **An agent must NOT finalize a
Canva product before the seller returns the template link.**

1. **ENGINE (automatable / CLI):** `etsy-engine canva prepare "<niche>"`
   → `architect.plan` → N full-design images (Raywake, full-bleed 2:3) → `set.html` + delivery PDF
   (placeholder link) + honest listing + `manifest.json`.
2. **AGENT SESSION (Canva MCP) — the agent does this, then hands back the edit link directly:**
   `import-design-from-url` needs a **public HTTPS** file and does not take `.html`. Build a
   **multi-page PDF from the design PNGs** and host it at any public HTTPS URL you control
   (object storage, a CDN, a release asset):
   `Image.open(design_i.png).save('set_design.pdf', save_all=True, append_images=[...])` →
   upload → `import-design-from-url(url=<pdf url>, intended_design_type="a4")`.
   Pages come in at 2:3 (1365×2048) with the images as **editable image fills, full-bleed** (verify
   via `start-editing-transaction`: every `fills[].editable:true`, then `cancel-editing-transaction`).
   **Deliver the design `edit_url` to the seller directly.**
3. **SELLER (manual, the final touch):** run **Magic Layers** on each page → **Share → Template
   link**. **⛔ THE AGENT WAITS HERE.** Do not build mockups, the delivery PDF, or the Etsy draft
   until the seller sends the template link — the product cannot be finalized without it.
4. **ENGINE (after the link):** `etsy-engine canva publish --dir <out> --link <template_link>`
   → i2i mockups (faithful, with the honest "Editable Canva Template" badge) → delivery PDF rebuilt
   with the real link → **Etsy DRAFT**. The seller ticks "made with an AI generator" and publishes
   (drafts only, RULES §B4).

## 🎨 Design intelligence — diversify + match the niche (2026-07-05)

Every Canva product used to come out the SAME (cream + serif + botanical florals) even when the
chosen aesthetic was `modern_minimal`, because `poster.build_prompt` HARDCODED "elegant serif
display title" + "botanical accents framing top and bottom" and never injected the aesthetic's
palette/fonts. Fixed in two layers:

1. **Design-system-driven prompt.** `build_prompt` composes the look from a design system's
   `art_style` + `type_prompt` (serif vs bold sans vs rounded) + `frame_prompt` (florals / clean
   grid / playful border / retro band) + explicit `palette` hexes. Nothing is hardcoded to
   serif/botanical anymore.
2. **Competitor design research** (`research.design_brief`): distills the niche's winning design
   language from real top-seller hero images (one cached vision call).
3. **Shared ART DIRECTOR** (`design/art_director.art_direction` — the SAME module the PDF line uses;
   the Canva line injects its own aesthetic as the soft fallback so there is no dependency on
   `canva/`). Given the niche + concept + the research, it writes a **bespoke** design system per
   product (custom palette, font pairing, illustration style, framing) instead of snapping to one of
   the 5 presets. `produce.prepare` runs research -> art director -> `poster` (passing `direction`).
   A forced `--aesthetic` skips the art director and uses that preset. Robust: strict-JSON prompt +
   one retry, then soft-fallback to the fixed aesthetic (poster never breaks).

The 5 `design.py` aesthetics are now a **floor/fallback**, not the default look. Verified end to end,
same engine, three totally different products: a minimal sage budget planner, a bright cartoon dino
birthday invite, and a pastel spooky-cute Halloween invitation.

Cost: ~one vision + one text call per new product (research cached). This is the anti-"waste credits
on a generic product" lever — spend a cent on design intelligence so the pages fit the market.

## Magic-Layers design rules (baked into `poster.build_prompt`)

Magic Layers converts flat / high-contrast / distinct-element art best and struggles with
dense/small text, so every design: flat illustrated style (never photorealistic); high
contrast; **large, well-spaced text, few words**; distinct icon/section boundaries; **FULL
BLEED** at **2:3 (1024×1536)** so the Canva page matches (no white gaps); correct spelling.

## Package (`etsy_engine.canva`)

- **design.py** — 5 distinct **aesthetics** (botanical / editorial / modern_minimal / playful /
  retro), each with its OWN palette + font pairing + `art_style` + `type_prompt` + `frame_prompt`
  so they render genuinely differently; `MAGIC_LAYERS_RULES`, brand (`CONTACT_EMAIL=…`, `POSTER_SIZE`).
- **research.py** — `design_brief(niche)`: pulls the current top-seller hero images for the niche
  (Etsy API), tiles them into ONE collage, and asks Claude vision for the niche's WINNING design
  language (palette, motifs, layout, typography) + a recommended aesthetic + a concrete brief. One
  vision call per niche, cached to `data/canva_style_briefs.json`. Steers `poster` so we design to
  buyer taste, not one generic look. Fails soft (no images/key -> generic).
- **architect.py** — `plan(niche)`: **market-informed** LLM → a coherent 3–6 page set whose page
  STRUCTURE fits the product type (a guest book gets sign-in/memory pages, not a generic host kit).
  Reads the niche's `top_selling_titles` + `market_scope` and runs a **critic pass** (reuses
  `product.architect.market_scope` + `critique_bundle`) that forces one revision on a me-too plan.
  Attaches `spec['_market']` (median price etc.) for the pricing step.
- **poster.py** — `generate`: one full-design, full-bleed, Magic-Layers-ready image per page.
- **produce.py** — `prepare(niche)`: plan → image per page → `set.html` + delivery + listing + manifest.
- **mockups.py** — `build_all`: reference-faithful i2i scene mockups (hero / lifestyle / contents)
  + flat previews. "Editable Canva Template" badge is allowed here (§H5).
- **delivery.py** — `build_pdf(title, link)`: branded buyer PDF (how-to, review request, contact, link).
- **publish.py** — `create_draft`: the Etsy DRAFT (images + delivery PDF + honest copy) via the shared client.
- **copy.py** — honest `listing_copy()`. `render.py`/`art.py` = retired HTML path (shim + tests only).

- **detect.py** — `scan()` / `canva_suitability()`: route by **the rule** below. Canva only for
  identity/event-personalized products (signs, invitations, weddings, host/guest, classroom, gift
  tags); pure-print activities (coloring, clipart, SVG, games, word search) AND fill-in/tick-off
  products (trackers, checklists, planners, logs, journals, bucket lists) stay on the PDF line.
  Matching is plural-tolerant so "gift tags"/"welcome signs" route like their singular signal.

## ⭐ THE ROUTING RULE — edit-personalization vs use-personalization

The single question that decides PDF vs Canva:

> **Does the buyer swap in their OWN unique data, or do they just fill in / tick off a generic sheet?**

- **Swap-my-name (name, date, event, venue, brand, prices)** → **Canva-editable.** The output is a
  personalized artifact (a sign that says *The Smith Family*, an invite with the party details). PDF
  can't do this; the editable template is the whole value. → welcome signs, invitations, weddings,
  seating charts, gift tags, price lists, name/quote wall-art, classroom name tags.
- **Fill-in / tick-off (the buyer writes on it or uses it over time)** → **print-at-home PDF** (or an
  interactive doc). Opening Canva to tick "visited France" is friction, not value. → trackers,
  checklists, planners, logs, journals, bucket lists, meal plans, chore charts.

⚠️ **Why this rule exists:** a "planner/tracker/checklist" *keyword* used to force Canva routing, so
"world checklist tracker printable" was mis-produced as a 5-page editable set no buyer would ever
open Canva to use. Design quality masked a missing job-to-be-done. The rule now lives in
`canva.detect.canva_suitability` (fill-in terms are in `EXCLUDE`; there is no `planner` signal
bucket) and is locked by tests in `tests/test_canva_detect.py`.

**Auto-routing — the MAIN pipeline decides the format per trend.** `etsy-engine run` (→ `architect`)
now classifies EACH top trend by the rule above: swap-my-name products route to the Canva line and
are **queued**; everything else (fill-in products + pure-print) builds a print-at-home PDF exactly as
before (the PDF branch is byte-identical). The decision lives in the main flow, driven by the trend —
not a separate command. `--no-canva` forces pure-PDF.

Full loop: `etsy-engine run` (routes per trend) → `canva queue` (see the Canva-routed trends) →
`canva produce-queue` (design sets) → Claude import → **seller Magic Layers** → `canva publish --dir
<out> --link <template_link>`. (`canva scan` is an ad-hoc live preview of what would route; `canva
prepare "<niche>"` produces one niche on demand.)

## Honesty gate (RULES §H5)

"editable"/"Canva" appear only for products that ship a real template. Canva-line copy comes from
`canva.copy.listing_copy` and mockups from `canva.mockups` (both honest by construction) and never
route through `seo/writer.py` or the PDF mockup prompts, so the primary PDF line's editable/Canva
bans stay fully in force.

## Status

- ✅ Full pipeline live + integrated (`etsy_engine.canva` + `canva` CLI, 93 tests). First real draft:
  a live draft (Airbnb host kit, 5 editable pages, i2i mockups).
- ✅ Auto-detection + routing (`canva scan`): flags Canva-suitable trends from the live scan and
  `--produce N` auto-prepares them, stopping at the seller's Magic Layers step. Verified on the live
  DB (wedding welcome signs, gift tags, invitations, seating charts…).
- ✅ Routing rule hardened (2026-07-05): fill-in/tick-off products (trackers, checklists, planners,
  logs) now correctly stay on the PDF line; plural terms route like their singular signal. Fixes the
  mis-routed "world checklist tracker printable". Locked by `tests/test_canva_detect.py`.
- ✅ Engine hardening sprint (2026-07-05, 93 tests): (1) **market-informed architect + critic** so
  the page STRUCTURE fits the product type; (2) **pre-handoff text QC** on every poster page with one
  gated regen (`qc.assess_text` + `produce._gen_page_qc`); (3) **market-driven pricing** from the
  niche median × page count (`publish.market_price`, no more flat $11.99); (4) **hero thumbnail
  auto-redo gate** on both lines; (5) a **single pre-publish gate** (`publish/gate.py`) both lines
  route through (tags ≤20/≤13, title rules, honesty) so a draft can't 400 on tags again; (6)
  first-class **single-asset regen** (`generator.regenerate_item`, `etsy-engine regen-item`); (7)
  **cross-language dedup** (`history._normalize`: "copa do mundo" now collides with "world cup").
  Verified end to end: a "christmas welcome sign" prepare produced a bespoke "cozy farmhouse cocoa
  bar" set (not botanical), priced $12.99 from the $9 niche median.
- ✅ Impeccable-audit fix pass (2026-07-05, 99 tests): technical audit (13/20); fixed all 6 findings:
  per-image **alt text** on Canva listings (`_image_alt`, WCAG 1.1.1 + SEO); **>=2000px listing
  images** (`_ensure_min_px` Lanczos-upscale to Etsy's zoom threshold) + a US Letter/A4 fit note in
  the delivery PDF; **contrast enforced** in `qc.assess_text` (low `legible_contrast` = hard fail ->
  regen); **cached** `market_intel` + `top_listing_titles` (keyword caches); **fallback rebased off
  the slop lane** (`DEFAULT_AESTHETIC` = modern_minimal, preset serifs Bodoni/Prata/Spectral/Caslon
  not the reflex-reject Cormorant/Playfair); raw `.png` dropped beside the listing `.jpg`.
- Impeccable-critique fix pass (2026-07-05, 95 tests): the critique (30/40, snapshot in
  `.impeccable/critique/`) flagged skin-deep variety. Fixed: (1) **layout vocabulary** — the architect
  now has 9 structures (welcome/sheet/checklist/two_column/timeline/stat/table/signin/statement) and
  `poster._content_brief` composes each DIFFERENTLY, so products vary in STRUCTURE not just palette;
  (2) **PAGE RULES** in the architect prompt: vary layouts (no four identical sheets), page 1 is
  always a usable artifact (never a "what's inside" ad), use the quote 'statement' page sparingly (no
  filler); (3) **contrast rule** (accent colors for large display only, body/labels stay ink-dark) in
  `MAGIC_LAYERS_RULES` + the art-director brief + a text-QC contrast dimension; (4) **niche-varied
  mockup scenes** (`_scenes_for`: wedding→venue easel, planner→desk, party→table, host→entryway…).
