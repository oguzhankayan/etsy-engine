# Etsy SEO playbook (2026) — encoded into `seo/`

Distilled from current Etsy SEO guidance (2025–2026). Drives `seo/keyword_research.py`
and `seo/writer.py`.

## How Etsy search ranks (2026)
1. **Query matching** — title, tags, and attributes are matched to the buyer's search.
2. **Listing quality score** — CTR, add-to-cart, favorites, sales push winners up.
3. **Semantic search** — the algorithm understands intent & word relationships, not
   just exact characters. Write like the customer talks.
4. **Recency** — now minor; don't churn-renew.

## Titles
- First **40 characters weighed most**; search UIs show only ~50–60 chars → **front-load
  the primary keyword + product type**.
- Structure: `[Primary Keyword] | [Secondary Keyword + modifier] | [Occasion / Recipient]`.
- **No keyword stuffing / repetition** — unique descriptive phrases, natural language.
- Hard cap 140 chars; aim ~120–135 to stay keyword-rich but readable.

## Tags (the engine of discovery)
- Use **all 13**. Each ≤ **20 characters**.
- **≥ 8 of 13 should be multi-word long-tail** (sellers who do see ~+47% conversion).
- Cover different **intent angles**: product synonyms, audience/recipient, occasion,
  style/aesthetic, use-case, format (e.g. "instant download", "pdf printable").
- Don't waste a slot on a single broad word already in the title; don't near-duplicate.
- A long-tail phrase >20 chars: split across two tags at a sensible boundary, or drop.

## Description
- **First ~160 characters matter** (Google snippet + Etsy weighting) → lead with a hook
  that contains the primary keyword naturally.
- Then: what's included (list), who it's for, instant-digital-download delivery, print
  notes (US Letter + A4, 300 DPI), personal-use terms.
- Natural language, not a keyword dump.

## Buyer-intent / gifting
- Gifting & "customized gifts" searches are major traffic drivers (+22% in 2026).
- Weave **occasion + recipient** terms where relevant (teacher gift, gift for mom, etc.).

## Our two-step implementation
1. `keyword_research.py` — Claude as an Etsy keyword researcher → structured set:
   primary keyword, product-type terms, long-tail buyer-intent phrases, occasions,
   recipients, styles, synonyms (each ≤20 chars where meant to be a tag).
2. `writer.py` — assembles title (formula), 13 tags (≥8 long-tail, all ≤20, deduped),
   description (160-char hook first), per-image alt text, FAQ. Hard limits enforced in code.

## Authoritative refinements (Etsy Seller Handbook, Aug 2025)

From Etsy's own "Ultimate Guide to Etsy Search", "Keywords 101", and "Add
Attributes" articles:

- **Title position does NOT affect ranking.** Etsy reads each |-separated phrase
  regardless of order. So front-loading is purely for HUMAN clarity (mobile
  scanning). Write **short, clear, descriptive** titles that lead with what the
  item IS; avoid long keyword dumps (they confuse buyers).
- **Descriptions factor into ranking** (query-matching phase). Put a few top
  keywords naturally in the **first 1-2 sentences**; don't copy the title or list
  keywords.
- **Categories + Attributes act like tags** AND power the filter sidebar — a
  listing only appears in a filtered search if it HAS that attribute. Add the most
  specific category, then all relevant attributes (color, occasion, etc.).
  → implemented in `publish/attributes.py` (Primary/Secondary color from the
  design system, Occasion/Holiday/Style from the product).
- **Don't repeat in tags what's already in categories/attributes** — it frees tag
  slots. Don't repeat near-duplicate roots ("octopus art print" vs "octopus
  print"). **Ignore plurals** (root-word matching). Use all 13, multi-word.
- **Diversify tags across 7 types:** descriptive, materials/techniques,
  who-it's-for, shopping-occasion, solution-oriented, style, size/format.
  → encoded in `keyword_research.py` + `writer.build_tags` (near-dup-root filter).

Sources: Etsy Seller Handbook — Ultimate Guide to Etsy Search, Keywords 101, Add
Attributes (Aug 2025); eRank long-tail guide; Marmalead 2026 algorithm.
