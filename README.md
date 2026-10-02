# etsy-engine

**An open-source engine that finds what Etsy buyers are already paying for, designs an
original printable product for it, shoots the listing photos, writes the SEO, and
drafts the listing in your shop.**

This isn't a prompt template. It's the engine we ran a real Etsy shop on: trend
intake, demand validation against live Etsy listings, product design, page QC,
reference-faithful mockups, and SEO, all as a single pipeline with a SQLite memory
and a learning loop.

<!-- TODO: add a product grid / sales screenshot here -->

```bash
etsy-engine demo "teacher appreciation week"
# -> output/1/  4 print-ready pages, listing photos, listing.md (title, 13 tags, description)
```

> **Disclosure:** etsy-engine is built and maintained by the team behind
> [Raywake](https://raywake.com), and Raywake is the image backend. You need a Raywake
> API key and an Anthropic API key, nothing else, to make your first product. The
> code is MIT: fork it and wire in whatever you like.

---

## What it does

```text
 trends ──► score ──► validate ──► architect ──► generate ──► mockups ──► seo ──► publish
 Google,    Claude    live Etsy     picks the     pages via     the REAL    13 tags,   Etsy
 Reddit,    6-factor  demand,       format the    Raywake,      pages in    title,     DRAFT
 X, ideas   + IP gate competition,  niche buys    QC'd by       styled      desc,      (never
                      price         (kit, print,  Claude vision scenes      alt, FAQ   auto-live)
                                    party set…)   pick-best
```

- **Demand first.** Every idea is checked against live Etsy listings for demand,
  competition, beatability and the median price before a single image is generated.
  An expected-value gate blocks products projected to lose money, so no credits are
  spent on them.
- **Fits the format to the niche.** If a niche buys wall art, you get a print. If it
  buys planner kits, you get a cohesive 6–10 page system. Party niches get party
  sets. The architect reads top-seller titles to learn the *structure* and never
  copies their content.
- **Honest listings.** Mockups are made by passing your actual pages to the image
  model as references, so the photos show exactly what the buyer downloads. Contents
  grids are pixel-exact. Page counts are never invented. IP checks run on both the
  idea and the generated pixels.
- **Print-ready output.** 1536×2048 pages, 300-DPI JPEGs, a single `bundle.pdf` and
  an `individual-pages.zip`, which fit inside Etsy's 5-file limit.
- **Learns.** `metrics` + `learn` correlate what sold with how it was scored and
  re-tune the weights. Proven and seasonal listings are protected from pruning and
  kept renewed.
- **Canva line (optional).** For "put your own name on it" niches (weddings, signs,
  invitations), it produces Canva-editable template sets instead of flat PDFs.

## Quickstart

```bash
git clone https://github.com/<you>/etsy-engine && cd etsy-engine
python3 -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env            # add RAYWAKE_API_KEY + ANTHROPIC_API_KEY
.venv/bin/etsy-engine credits   # confirms the Raywake key works
.venv/bin/etsy-engine demo "camping meal planner"
```

The demo caps the bundle at 4 pages (`--max-pages 0` for the full plan) and prints the
output folder. Every image is quoted before it starts. `etsy-engine credits` shows
your balance and what you've spent.

Get keys: **Raywake** → [raywake.com](https://raywake.com) (studio → API keys, scopes
`generate` + `jobs:read`) · **Anthropic** → [console.anthropic.com](https://console.anthropic.com).

## Going live on Etsy

Add your Etsy app keys (see [docs/SETUP.md](docs/SETUP.md), which also covers the
`keystring:shared_secret` gotcha), then:

```bash
.venv/bin/etsy-engine etsy-auth                    # one-time OAuth
.venv/bin/etsy-engine run --full                   # collect → score → validate → architect → generate → mockups → seo
.venv/bin/etsy-engine review                       # what the engine picked and why
.venv/bin/etsy-engine publish --product-id 3       # creates a DRAFT
```

Or end to end: `etsy-engine produce -n 3`, which alternates evergreen (proven demand)
and viral (rising trend) lanes.

Drafts only, by design. Open each draft, tick Etsy's **"With an AI generator"** option
(it isn't available in the API), and publish.

## Commands

| | |
|---|---|
| `demo "<niche>"` | one finished product, no Etsy account |
| `run [--full]` | the discovery funnel, optionally through SEO |
| `collect` · `score` · `validate` · `architect` | discovery stages |
| `generate` · `mockups` · `seo` | production stages (queue-wide; check `report` first) |
| `publish --product-id N` | Etsy draft |
| `produce -n N` | full pipeline for N products, alternating lanes |
| `regen-item --item-id N` | re-roll one page without touching the rest |
| `metrics` · `learn` · `rank-track` · `optimize` · `renew` | after listings are live |
| `canva prepare "<niche>"` | Canva-editable template set ([docs/canva-line.md](docs/canva-line.md)) |
| `credits` | Raywake balance + local spend |

Full reference: [docs/PIPELINE.md](docs/PIPELINE.md). Operating rules and the reasoning
behind them: [RULES.md](RULES.md). SEO playbook: [docs/etsy-seo.md](docs/etsy-seo.md).

## Images

All image generation goes through one file,
[`src/etsy_engine/generate/raywake.py`](src/etsy_engine/generate/raywake.py), in three
steps: quote → generate (idempotent) → poll. The default model is **GPT Image 2.5
Sunburst**. It renders the printable text directly and uses its edit mode for
reference-faithful mockups. To try another model from the Raywake catalog, set
`RAYWAKE_MODEL`.

## Layout

```text
src/etsy_engine/
  sources/     trend intake (Google, Reddit, X via Grok, rotating idea catalog)
  scoring/     LLM scoring, IP gate, Etsy market validation, EV gate
  product/     architect: format routing + bundle design
  design/      art director (one design system per product) + prompt builder
  generate/    Raywake client, page generation, QC, letter banners
  mockups/     reference-faithful listing photos
  seo/         keyword research + listing writer
  publish/     Etsy client, draft publishing, shop profile
  learning/    metrics, weight tuning, rank tracking, optimizer
  canva/       Canva-editable product line
```

## Contributing

Issues and PRs are welcome. Run `.venv/bin/pip install -e '.[dev]' && .venv/bin/pytest -q`
before opening a PR. The tests use a throwaway database and never call paid APIs.

## License

MIT. See [LICENSE](LICENSE). You are responsible for following Etsy's policies,
including its rules on AI-generated content and intellectual property.
