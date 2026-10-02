"""Thin Anthropic client wrapper shared by scorer, architect, and SEO writer.

Centralizes the API key check, model selection, and a helper that asks Claude to
return strict JSON (with a forgiving parser for fenced/extra text).
"""
from __future__ import annotations

import json
import re
import time

from .config import settings, DATA_DIR


def _client():
    settings.require("anthropic_api_key")
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


# --- Cost ledger (mirrors generate/raywake.py's per-image ledger) ----------
SPEND_LOG = DATA_DIR / "anthropic_spend.jsonl"  # append-only per-call cost ledger

# Claude Sonnet 5 sticker pricing (USD / 1M tokens). The $2/$10 intro ran through
# 2026-08-31; sticker is the durable, slightly-conservative default. Tokens are
# logged too, so cost can always be recomputed if a rate changes.
_PRICE_USD_PER_MTOK = {
    "claude-sonnet-5": {"in": 3.00, "out": 15.00, "cache_write": 3.75, "cache_read": 0.30},
}
_FALLBACK_RATE = {"in": 3.00, "out": 15.00, "cache_write": 3.75, "cache_read": 0.30}


def _record_llm_spend(usage, model: str, kind: str) -> None:
    """Append one Anthropic call's token usage + USD cost to the ledger, so LLM
    spend is trackable per run (the cost driver is QC vision — ~10 calls/product)."""
    if usage is None:
        return
    rate = _PRICE_USD_PER_MTOK.get(model, _FALLBACK_RATE)
    itok = int(getattr(usage, "input_tokens", 0) or 0)
    otok = int(getattr(usage, "output_tokens", 0) or 0)
    cw = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cost = (itok * rate["in"] + otok * rate["out"]
            + cw * rate["cache_write"] + cr * rate["cache_read"]) / 1_000_000
    line = {"time": int(time.time()), "model": model, "kind": kind,
            "input_tokens": itok, "output_tokens": otok,
            "cache_write_tokens": cw, "cache_read_tokens": cr,
            "cost_usd": round(cost, 6)}
    try:
        SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SPEND_LOG.open("a") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError:
        pass


def total_spend() -> dict:
    """Sum the Anthropic cost ledger -> {total_usd, calls, input_tokens, output_tokens}."""
    total, n, itok, otok = 0.0, 0, 0, 0
    if SPEND_LOG.exists():
        for ln in SPEND_LOG.read_text().splitlines():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            total += float(d.get("cost_usd") or 0)
            itok += int(d.get("input_tokens") or 0)
            otok += int(d.get("output_tokens") or 0)
            n += 1
    return {"total_usd": round(total, 4), "calls": n,
            "input_tokens": itok, "output_tokens": otok}


def complete_json(system: str, user: str, max_tokens: int = 4096) -> dict | list:
    """Send a prompt and parse the response as JSON.

    Claude is instructed (via `system`) to reply with JSON only; we still strip
    code fences and grab the first {...} / [...] block defensively.
    """
    client = _client()
    last: Exception | None = None
    for attempt in range(3):  # retry transient malformed-JSON replies
        msg = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system + ("\n\nReturn ONLY valid JSON." if attempt else ""),
            messages=[{"role": "user", "content": user}],
        )
        _record_llm_spend(getattr(msg, "usage", None), settings.anthropic_model, "text")
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        try:
            return _parse_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            last = e
    raise last


def vision_json(
    system: str, user: str, image_bytes: bytes,
    media_type: str = "image/jpeg", max_tokens: int = 1024,
) -> dict | list:
    """Send an image + prompt and parse the JSON reply. Used by QC (Agent 8).
    Uses the cheaper vision model (QC just checks text/alignment) to save cost."""
    import base64

    client = _client()
    msg = client.messages.create(
        model=settings.anthropic_vision_model or settings.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {
                "type": "base64", "media_type": media_type,
                "data": base64.standard_b64encode(image_bytes).decode(),
            }},
            {"type": "text", "text": user},
        ]}],
    )
    _record_llm_spend(getattr(msg, "usage", None),
                      settings.anthropic_vision_model or settings.anthropic_model, "vision")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return _parse_json(text)


def _parse_json(text: str) -> dict | list:
    text = text.strip()
    # strip ```json ... ``` fences if present
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # grab first balanced-looking JSON array/object
        m = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        raise
