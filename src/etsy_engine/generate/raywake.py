"""Raywake image client — the engine's image generator.

Every image in the pipeline (printable pages, banners, Canva posters, listing
mockups) goes through `RaywakeClient.generate(...)`, which returns raw image bytes.

API contract (https://raywake.com/docs):
  auth:  Authorization: Bearer RAYWAKE_API_KEY
  1. POST /v1/quotes   {"model", "input"}                      -> {"quote_id", "credits", ...}
  2. POST /v1/generate {"model", "quote_id", "input"}  + Idempotency-Key header
     (?wait=true blocks until a terminal state, up to the server deadline)
  3. GET  /v1/jobs/{job_id}                                     -> {"status", "outputs": [{"url"}]}

Billing rules this client respects:
  - Starting a generation reserves credits; failure releases them.
  - A timeout is NOT proof of failure: we retry with the SAME Idempotency-Key, which
    returns the existing job instead of starting (and paying for) a new one.
  - `needs_review` / `needs_reconciliation` / `submission_unknown` are never treated as
    success and never auto-resubmitted.

Default model: GPT Image 2.5 Sunburst — `.../text-to-image` for new images and
`.../edit` when reference images are passed (faithful product mockups).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid

import requests

from ..config import DATA_DIR, settings

SPEND_LOG = DATA_DIR / "raywake_spend.jsonl"  # append-only per-image credit ledger

# Portrait ~US Letter ratio (8.5x11) at print resolution — the default printable size.
DEFAULT_SIZE = "1536x2048"

ERRORS = {
    400: "Bad request (invalid input for this model)", 401: "Unauthorized (bad/revoked API key)",
    402: "Insufficient credits — top up at https://raywake.com/pricing",
    403: "Forbidden (API key is missing a scope: needs generate + jobs:read)",
    404: "Not found", 409: "Conflict (quote expired/changed input or idempotency clash)",
    413: "Request too large", 429: "Rate limited",
}
TRANSIENT = {429, 500, 502, 503, 504}
DONE = {"succeeded", "completed"}
FAILED = {"failed", "canceled", "cancelled", "rejected", "expired"}
HELD = {"needs_review", "needs_reconciliation", "submission_unknown"}

# Output URLs keyed by sha256 of the bytes we returned, so `hosting.public_url()` can
# hand a freshly generated image to a service that needs an HTTPS link (Canva import).
_output_urls: dict[str, str] = {}
_lock = threading.Lock()


class RaywakeError(RuntimeError):
    pass


class RaywakeJobUnknown(RaywakeError):
    """A job may exist (and may be charged) but its outcome is unknown. Never auto-retried:
    a new submission could pay twice. Check the job id in the Raywake studio."""


def output_url_for(data: bytes) -> str | None:
    """The Raywake output URL for image bytes this process generated, if any."""
    with _lock:
        return _output_urls.get(hashlib.sha256(data).hexdigest())


def _image_size(size: str) -> dict | str:
    """'1536x2048' -> {"width": 1536, "height": 2048}; passes named presets through."""
    try:
        w, h = (int(x) for x in size.lower().split("x"))
        return {"width": w, "height": h}
    except (ValueError, AttributeError):
        return size


class RaywakeClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, edit_model: str | None = None,
                 quality: str | None = None):
        self.api_key = api_key or settings.raywake_api_key
        self.base = (base_url or settings.raywake_base_url).rstrip("/")
        self.model = model or settings.raywake_model
        self.edit_model = edit_model or settings.raywake_edit_model
        self.quality = quality or settings.raywake_quality

    # --- http ---------------------------------------------------------------
    def _headers(self, idempotency_key: str | None = None) -> dict:
        if not self.api_key:
            settings.require("raywake_api_key")
        h = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
             "User-Agent": "etsy-engine (+https://raywake.com)"}
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    def _request(self, method: str, path: str, *, body: dict | None = None,
                 idempotency_key: str | None = None, params: dict | None = None,
                 timeout: int = 60, retries: int = 4) -> dict:
        """JSON request with backoff on transient errors. Safe to retry because quotes
        are free and generate carries a stable Idempotency-Key."""
        last = ""
        for attempt in range(retries):
            try:
                resp = requests.request(method, f"{self.base}{path}", json=body, params=params,
                                        headers=self._headers(idempotency_key), timeout=timeout)
            except requests.RequestException as e:  # timeout / connection blip
                last = str(e)[:160]
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code < 300:
                return resp.json()
            if resp.status_code in TRANSIENT:
                last = f"{resp.status_code} {ERRORS.get(resp.status_code, '')}"
                wait = resp.headers.get("Retry-After")
                time.sleep(float(wait) if wait and wait.isdigit() else 3 * (attempt + 1))
                continue
            raise RaywakeError(f"{method} {path} -> {resp.status_code} "
                               f"{ERRORS.get(resp.status_code, 'Error')}: {resp.text[:300]}")
        raise RaywakeError(f"{method} {path} failed after {retries} attempts: {last}")

    # --- public surface -----------------------------------------------------
    def generate(self, prompt: str, size: str = DEFAULT_SIZE, timeout: int = 300,
                 retries: int = 3, image_urls: list[str] | None = None) -> bytes:
        """Generate one image and return its bytes.

        image_urls: optional reference images (https URLs or data URIs, see hosting.py).
        When given, the edit model reproduces the EXACT product in a new scene — used
        for honest listing mockups."""
        from .hosting import fit_references

        model = self.edit_model if image_urls else self.model
        inp: dict = {"prompt": prompt, "image_size": _image_size(size), "quality": self.quality,
                     "num_images": 1, "output_format": "jpeg"}
        if image_urls:
            inp["image_urls"] = fit_references([u for u in image_urls if u][:16])

        last = ""
        for attempt in range(max(1, retries)):
            try:
                return self._run(model, inp, timeout)
            except RaywakeJobUnknown:
                raise
            except RaywakeError as e:
                # Only a clean rejection or a FAILED job (credits released) is safe to retry,
                # and only if it isn't a hard failure (auth, credits, bad input).
                last = str(e)
                if any(f" {c} " in last for c in ("400", "401", "402", "403", "413")):
                    raise
                time.sleep(3 * (attempt + 1))
        raise RaywakeError(f"generation failed after {retries} attempts: {last[:300]}")

    def _run(self, model: str, inp: dict, timeout: int) -> bytes:
        quote = self._request("POST", "/v1/quotes", body={"model": model, "input": inp})
        key = str(uuid.uuid4())  # one key per intended image; reused on every retry below
        try:
            job = self._request("POST", "/v1/generate", params={"wait": "true"},
                                body={"model": model, "quote_id": quote["quote_id"], "input": inp},
                                idempotency_key=key, timeout=timeout)
        except RaywakeError as e:
            if "failed after" in str(e):   # transient errors exhausted: the job may exist
                raise RaywakeJobUnknown(f"generate outcome unknown (Idempotency-Key {key}): {e}") from e
            raise                          # a definite rejection — nothing was started
        job = self._await(job, timeout)
        url = job.get("image_url") or next((o.get("url") for o in job.get("outputs") or []
                                            if o.get("url")), None)
        if not url:
            raise RaywakeJobUnknown(f"job {job.get('job_id')} succeeded without an output url")
        try:
            data = self._download(url)
        except RaywakeError as e:
            raise RaywakeJobUnknown(f"job {job.get('job_id')} succeeded but download failed: {e}") from e
        with _lock:
            _output_urls[hashlib.sha256(data).hexdigest()] = url
        _record_spend(job.get("job_id"), model, job.get("credits") or quote.get("credits"))
        return data

    def _await(self, job: dict, timeout: int) -> dict:
        deadline = time.time() + timeout
        while True:
            status = (job.get("status") or "").lower()
            if status in DONE:
                return job
            if status in FAILED:
                raise RaywakeError(f"job {job.get('job_id')} {status}: {job.get('error') or ''}")
            if status in HELD:
                # Credits stay reserved until Raywake settles it; resubmitting could double-pay.
                raise RaywakeJobUnknown(f"job {job.get('job_id')} held ({status}) — check it at "
                                        "https://raywake.com before retrying")
            if time.time() > deadline:
                raise RaywakeJobUnknown(f"timed out waiting for job {job.get('job_id')} ({status})")
            time.sleep(4)
            try:
                job = self._request("GET", f"/v1/jobs/{job['job_id']}")
            except RaywakeError as e:
                raise RaywakeJobUnknown(f"lost track of job {job.get('job_id')}: {e}") from e

    def _download(self, url: str) -> bytes:
        last = ""
        for attempt in range(4):
            try:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                return r.content
            except requests.RequestException as e:
                last = str(e)[:160]
                time.sleep(2 * (attempt + 1))
        raise RaywakeError(f"download failed: {last}")

    def credits(self) -> dict:
        """Current Raywake wallet (credit balance)."""
        return self._request("GET", "/v1/wallet")


def _record_spend(job_id, model: str, credits) -> None:
    """Append this image's credits to the local ledger (see `total_spend`)."""
    try:
        cr = float(credits or 0)
    except (TypeError, ValueError):
        cr = 0.0
    line = {"time": int(time.time()), "job_id": job_id, "model": model, "credits": cr}
    try:
        SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SPEND_LOG.open("a") as fh:
            fh.write(json.dumps(line) + "\n")
    except OSError:
        pass


def total_spend() -> dict:
    """Sum the local credit ledger -> {credits, images}."""
    total, n = 0.0, 0
    if SPEND_LOG.exists():
        for ln in SPEND_LOG.read_text().splitlines():
            try:
                total += float(json.loads(ln).get("credits") or 0)
                n += 1
            except (ValueError, TypeError):
                continue
    return {"credits": round(total, 2), "images": n}
