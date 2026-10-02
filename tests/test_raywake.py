"""Raywake client: quote -> generate (idempotent) -> poll -> download, plus reference fitting."""
import base64
import io

import pytest
from PIL import Image

from etsy_engine.generate import hosting, raywake
from etsy_engine.generate.raywake import RaywakeClient, RaywakeError


class FakeResp:
    def __init__(self, status=200, payload=None, content=b"", headers=None):
        self.status_code, self._payload, self.content = status, payload, content
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise raywake.requests.HTTPError(self.status_code)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(raywake, "SPEND_LOG", tmp_path / "spend.jsonl")
    monkeypatch.setattr(raywake.time, "sleep", lambda *_: None)
    return RaywakeClient(api_key="rw_test", base_url="https://api.example")


def _wire(monkeypatch, responses, calls):
    def fake_request(method, url, json=None, params=None, headers=None, timeout=None):
        calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return responses.pop(0)
    monkeypatch.setattr(raywake.requests, "request", fake_request)
    monkeypatch.setattr(raywake.requests, "get", lambda url, timeout=None: FakeResp(content=b"IMG"))


def test_text_to_image_happy_path(client, monkeypatch):
    calls = []
    _wire(monkeypatch, [
        FakeResp(payload={"quote_id": "q1", "credits": 12}),
        FakeResp(payload={"job_id": "j1", "status": "queued"}),
        FakeResp(payload={"job_id": "j1", "status": "succeeded", "credits": 12,
                          "outputs": [{"url": "https://cdn.example/out.jpg", "type": "image"}]}),
    ], calls)
    assert client.generate("a planner page", size="1536x2048") == b"IMG"
    quote, gen = calls[0]["json"], calls[1]["json"]
    assert quote["model"].endswith("sunburst/text-to-image")
    assert quote["input"]["image_size"] == {"width": 1536, "height": 2048}
    assert gen["quote_id"] == "q1" and gen["input"] == quote["input"]
    assert calls[1]["headers"]["Idempotency-Key"]
    assert calls[1]["headers"]["Authorization"] == "Bearer rw_test"
    assert raywake.output_url_for(b"IMG") == "https://cdn.example/out.jpg"
    assert raywake.total_spend()["credits"] == 12


def test_references_switch_to_edit_model(client, monkeypatch):
    calls = []
    _wire(monkeypatch, [
        FakeResp(payload={"quote_id": "q", "credits": 20}),
        FakeResp(payload={"job_id": "j", "status": "succeeded", "image_url": "https://x/y.jpg"}),
    ], calls)
    client.generate("mockup", image_urls=["https://x/ref.jpg"])
    assert calls[0]["json"]["model"].endswith("sunburst/edit")
    assert calls[0]["json"]["input"]["image_urls"] == ["https://x/ref.jpg"]


def test_retry_after_timeout_reuses_idempotency_key(client, monkeypatch):
    calls, seq = [], []

    def fake_request(method, url, json=None, params=None, headers=None, timeout=None):
        calls.append(headers.get("Idempotency-Key"))
        if url.endswith("/v1/quotes"):
            return FakeResp(payload={"quote_id": "q", "credits": 1})
        seq.append(1)
        if len(seq) == 1:
            raise raywake.requests.Timeout("slow")
        return FakeResp(payload={"job_id": "j", "status": "succeeded", "image_url": "https://x"})

    monkeypatch.setattr(raywake.requests, "request", fake_request)
    monkeypatch.setattr(raywake.requests, "get", lambda url, timeout=None: FakeResp(content=b"I"))
    client.generate("p")
    gen_keys = [k for k in calls if k]
    assert len(gen_keys) == 2 and gen_keys[0] == gen_keys[1]   # same job, never paid twice


def test_held_job_is_not_resubmitted(client, monkeypatch):
    calls = []
    _wire(monkeypatch, [
        FakeResp(payload={"quote_id": "q", "credits": 1}),
        FakeResp(payload={"job_id": "j", "status": "needs_review"}),
    ], calls)
    with pytest.raises(RaywakeError, match="held"):
        client.generate("p")
    assert len(calls) == 2


def test_poll_timeout_never_starts_a_second_job(client, monkeypatch):
    calls = []
    monkeypatch.setattr(raywake.time, "time", iter(range(0, 10_000, 500)).__next__)
    _wire(monkeypatch, [
        FakeResp(payload={"quote_id": "q", "credits": 1}),
        FakeResp(payload={"job_id": "j", "status": "running"}),
        FakeResp(payload={"job_id": "j", "status": "running"}),
    ] * 3, calls)
    with pytest.raises(raywake.RaywakeJobUnknown):
        client.generate("p", timeout=600)
    assert sum(c["url"].endswith("/v1/generate") for c in calls) == 1


def test_failed_job_is_retried_with_a_fresh_quote(client, monkeypatch):
    calls = []
    _wire(monkeypatch, [
        FakeResp(payload={"quote_id": "q1", "credits": 1}),
        FakeResp(payload={"job_id": "j1", "status": "failed", "error": "provider"}),
        FakeResp(payload={"quote_id": "q2", "credits": 1}),
        FakeResp(payload={"job_id": "j2", "status": "succeeded", "image_url": "https://x"}),
    ], calls)
    assert client.generate("p") == b"IMG"
    keys = [c["headers"].get("Idempotency-Key") for c in calls if c["url"].endswith("/v1/generate")]
    assert len(keys) == 2 and keys[0] != keys[1]


def test_insufficient_credits_fails_fast(client, monkeypatch):
    calls = []
    _wire(monkeypatch, [FakeResp(status=402, payload={"detail": "no credits"})], calls)
    with pytest.raises(RaywakeError, match="402"):
        client.generate("p")
    assert len(calls) == 1


def _jpeg(w=2000, h=2600):
    buf = io.BytesIO()
    Image.effect_noise((w, h), 80).convert("RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_upload_returns_data_uri_within_budget(tmp_path):
    p = tmp_path / "page.jpg"
    p.write_bytes(_jpeg())
    uri = hosting.upload(str(p))
    assert uri.startswith("data:image/jpeg;base64,")
    assert len(uri) <= hosting.BODY_BUDGET
    Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))   # still a valid image


def test_fit_references_shares_the_body_budget(tmp_path):
    p = tmp_path / "page.jpg"
    p.write_bytes(_jpeg())
    refs = [hosting.upload(str(p))] * 3 + ["https://x/remote.jpg"]
    fitted = hosting.fit_references(refs)
    assert fitted[-1] == "https://x/remote.jpg"
    assert sum(len(r) for r in fitted if r.startswith("data:")) <= hosting.BODY_BUDGET
