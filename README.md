<p align="center">
  <a href="https://raywake.com/?utm_source=github&utm_medium=etsy-engine&utm_campaign=oss&utm_content=readme-logo">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/assets/raywake-logo-dark.svg">
      <img src="docs/assets/raywake-logo-light.svg" alt="Raywake" width="200">
    </picture>
  </a>
</p>

<h1 align="center">etsy-engine</h1>

<p align="center">
  <a href="https://raywake.com/?utm_source=github&utm_medium=etsy-engine&utm_campaign=oss&utm_content=badge"><img alt="Images by Raywake" src="https://img.shields.io/badge/images%20by-Raywake-c3092d"></a>
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-222221"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-222221">
</p>

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

> **Built by the team behind [Raywake](https://raywake.com/?utm_source=github&utm_medium=etsy-engine&utm_campaign=oss&utm_content=disclosure).** Raywake is the image
> engine behind every page and listing photo here. All you need for your first product
> is a [Raywake API key](https://raywake.com/api-keys?utm_source=github&utm_medium=etsy-engine&utm_campaign=oss&utm_content=disclosure) and an Anthropic key. The code is MIT, so
> fork it and change anything you like.

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

Get keys: **Raywake** → [create an API key](https://raywake.com/api-keys?utm_source=github&utm_medium=etsy-engine&utm_campaign=oss&utm_content=quickstart) (scopes
`generate` + `jobs:read`) · **Anthropic** → [console.anthropic.com](https://console.anthropic.com).

## What a product costs

Each image is priced by a Raywake quote before it runs, and `etsy-engine demo` prints
the total when it finishes. A typical demo product is 4 pages plus 2 mockups (the
contents grid is free, built pixel-exact from your pages). That makes 6 images, or 7
if the hero thumbnail tests weak and gets one re-roll, plus a few cents of Claude
calls for planning, QC and SEO.

<!-- TODO: replace with a measured run: "teacher appreciation week" demo = N credits ≈ $X; sells for $Y on Etsy -->

Your balance and running spend are one command away: `etsy-engine credits`.
[Credit packs →](https://raywake.com/pricing?utm_source=github&utm_medium=etsy-engine&utm_campaign=oss&utm_content=readme-cost)

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

## Images: why Raywake

We built Raywake because this engine needed it: one API key and one credit balance
for image, video and audio models, with every job priced before it starts and safe
to retry. In etsy-engine that means:

- **No surprise bills.** Every image is quoted first, and a retry after a timeout
  reuses the same idempotency key, so a network blip never pays twice.
- **The right model for each job.** GPT Image 2.5 Sunburst renders printable text
  cleanly, and its edit mode reproduces your real pages inside mockup scenes.
- **One balance for the studio and the API.** Try a prompt in the
  [Raywake studio](https://raywake.com/?utm_source=github&utm_medium=etsy-engine&utm_campaign=oss&utm_content=readme-studio), then run it here.

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
