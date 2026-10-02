# Setup

## 1. Install

```bash
git clone <this repo> etsy-engine && cd etsy-engine
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

Python 3.11+.

## 2. Keys

| Key | Needed for | Where |
|-----|-----------|-------|
| `RAYWAKE_API_KEY` | every image (pages, mockups, banners) | [raywake.com/api-keys](https://raywake.com/api-keys?utm_source=github&utm_medium=etsy-engine&utm_campaign=oss&utm_content=setup). Scopes: `generate`, `jobs:read`. |
| `ANTHROPIC_API_KEY` | scoring, product design, page QC, SEO | [console.anthropic.com](https://console.anthropic.com) |
| `ETSY_API_KEY` + `ETSY_SHARED_SECRET` | real market validation + publishing | [etsy.com/developers](https://www.etsy.com/developers/your-apps) |
| `REDDIT_*`, `OPENROUTER_API_KEY`, `CONTEXT_DEV_API_KEY` | optional trend sources / enrichment | — |

Check the image key: `.venv/bin/etsy-engine credits` prints your Raywake balance.

With just Raywake + Anthropic you can run `etsy-engine demo "<niche>"`. Add Etsy
when you want demand validated against real listings and drafts created in your shop.

## 3. Images: how Raywake is used

`src/etsy_engine/generate/raywake.py` is the only image client. Every call:

1. **quotes** the exact model + input (`POST /v1/quotes`) — you see the credit cost
   before anything runs;
2. **starts** the job with a unique `Idempotency-Key` (`POST /v1/generate?wait=true`);
3. **polls** the job (`GET /v1/jobs/{id}`) and downloads the output.

A network timeout is retried with the *same* idempotency key, so a retry returns the
existing job instead of paying twice. Jobs held for review are never resubmitted.
Spend is logged to `data/raywake_spend.jsonl`.

Default model: **GPT Image 2.5 Sunburst** — `.../text-to-image` for pages and
`.../edit` for mockups, where the real product pages go in as reference images so
every listing photo shows exactly what the buyer downloads. Change it with
`RAYWAKE_MODEL` / `RAYWAKE_EDIT_MODEL`; any image model in the Raywake catalog that
takes `prompt` + `image_size` (and `image_urls` for edits) works.

## 4. Etsy

### Auth (one-time, interactive)

OAuth2 **PKCE**. Add `http://localhost:3003/oauth/callback` as a callback URL in your
Etsy app, then:

```bash
.venv/bin/etsy-engine etsy-auth     # browser opens -> Allow -> tokens saved to data/
.venv/bin/etsy-engine etsy-shop     # prints your user + shop id -> put it in ETSY_SHOP_ID
.venv/bin/etsy-engine etsy-taxonomy "planner"   # pick a category id -> ETSY_TAXONOMY_ID
```

Tokens live in `data/etsy_tokens.json` (gitignored) and refresh automatically.

### Gotchas that cost hours

- **`x-api-key` must be `keystring:shared_secret`.** Just the keystring returns
  `403 Shared secret is required in x-api-key header` on every call. Handled in
  `publish/etsy_client.py`; you only need both values in `.env`.
- **`when_made=2020_2026`, type `download`** — otherwise Etsy shows "Made to order".
- **Max 5 digital files.** The engine ships two: `bundle.pdf` (all pages) and
  `individual-pages.zip`.
- **Title:** `&` only once (later ones become "and").
- **Taxonomy id is required** to create a listing.

### AI disclosure — one part is manual

1. The description disclosure is appended automatically (`seo/writer.py`).
2. Etsy's **"How is this made? → With an AI generator"** option is **not in the API**.
   Tick it in the Etsy editor for each draft before publishing.

The engine only ever creates **drafts**. You review, tick the AI option, and publish.

## 5. Automation (optional, macOS)

`scripts/install_automation.sh` installs launchd jobs: daily metrics + rank tracking,
weekly learning loop + listing renewals.

## 6. Tests

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

Tests run against a throwaway database and never call paid APIs.
