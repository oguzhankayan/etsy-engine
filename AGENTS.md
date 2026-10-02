# AGENTS.md

Before changing or running the system, read in order:

1. **[README.md](README.md)** — what the engine does and how to run it.
2. **[RULES.md](RULES.md)** — non-negotiable operating rules (demand-first, drafts only,
   never reset the DB, honesty).
3. **[docs/PIPELINE.md](docs/PIPELINE.md)** — the implemented pipeline and exact commands.
   If another doc disagrees, this file plus the code wins.
4. **[docs/SETUP.md](docs/SETUP.md)** — keys, Etsy auth, and Etsy gotchas.

Then inspect `git status`, `src/etsy_engine/__main__.py`, and `src/etsy_engine/pipeline.py`.

Quick orientation:
- Python package `etsy_engine` in `src/`, CLI `etsy-engine`, SQLite at `data/engine.db`.
- Images: `generate/raywake.py` (quote → idempotent generate → poll). Never resubmit a job
  that is held for review; never retry a generate with a new idempotency key.
- Secrets are in `.env` (gitignored). `data/` and `output/` are gitignored.
- `generate`, `mockups`, and `seo` are queue-wide. Inspect product statuses first.
- Etsy's "With an AI generator" option is not in the API: drafts need a human to tick it.
