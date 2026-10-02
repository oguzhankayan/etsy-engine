"""Single pre-publish GATE for both product lines.

Validate + sanitize a listing to Etsy's HARD rules BEFORE any draft API call, so a draft never
dies on a 400 (a tag over 20 chars, a bad title) and never ships a dishonest claim. Shared by the
PDF publisher and the Canva publish path; the `line` picks the honesty rule (the PDF line ships
flat hand-write printables and must never claim editable/Canva, while the Canva line ships a real
template so it may). Consolidates checks that used to be scattered (or missing — the tags>20 -> 400
we hit shipped because the PDF body had no tag-length guard)."""
from __future__ import annotations

ETSY_TAG_MAXLEN = 20
ETSY_MAX_TAGS = 13
ETSY_TITLE_MAX = 140

# The PDF line must never CLAIM these in its title/tags (it is flat, write-in-by-hand).
_PDF_BANNED = ("editable", "canva", "customizable", "fillable", "personalize", "personalized")


def sanitize_title(title: str) -> str:
    """Etsy title rules: '&' at most once (later ones -> 'and'), collapse spaces, <=140 chars."""
    out: list[str] = []
    seen_amp = False
    for ch in title or "":
        if ch == "&":
            if seen_amp:
                out.append("and")
                continue
            seen_amp = True
        out.append(ch)
    return " ".join("".join(out).split())[:ETSY_TITLE_MAX]


def sanitize_tags(tags) -> list[str]:
    """Etsy tag rules: <=20 chars each, non-empty, de-duped (case-insensitive), max 13."""
    out: list[str] = []
    seen: set[str] = set()
    for t in tags or []:
        t = " ".join(str(t).split())
        k = t.lower()
        if t and len(t) <= ETSY_TAG_MAXLEN and k not in seen:
            out.append(t)
            seen.add(k)
        if len(out) == ETSY_MAX_TAGS:
            break
    return out


def check_listing(listing: dict, line: str = "pdf") -> tuple[dict, list[str]]:
    """Return (clean_listing, violations).

    clean_listing has a sanitized title + valid tags and is SAFE to send to Etsy. violations lists
    anything the caller should surface (empty title, dropped tags, a dishonest claim on the PDF line).
    """
    v: list[str] = []
    title = sanitize_title(listing.get("title") or "")
    if not title:
        v.append("empty title")
    raw_tags = listing.get("tags") or []
    tags = sanitize_tags(raw_tags)
    if not tags:
        v.append("no valid tags after sanitize")
    elif len(raw_tags) - len(tags) > 0:
        v.append(f"dropped {len(raw_tags) - len(tags)} invalid/oversize/duplicate tag(s)")
    if line == "pdf":
        hay = (title + " " + " ".join(tags)).lower()
        claimed = [w for w in _PDF_BANNED if w in hay]
        if claimed:
            v.append(f"PDF line dishonestly claims {claimed} in title/tags")
    return {**listing, "title": title, "tags": tags}, v
