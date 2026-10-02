"""Etsy client retry/backoff on 429 and transient 5xx."""
from __future__ import annotations

from etsy_engine.publish import etsy_client as ec


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.ok = status < 400
        self.headers = headers or {}
        self.content = b"{}"
        self.text = "{}"
        self._body = body or {}

    def json(self):
        return self._body


def test_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(ec.time, "sleep", lambda s: None)
    responses = [FakeResp(429, headers={"Retry-After": "1"}),
                 FakeResp(200, {"count": 7})]
    resp = ec._send_with_retry(lambda: responses.pop(0), "GET /x")
    assert resp.status_code == 200
    assert resp.json() == {"count": 7}


def test_gives_up_after_max_tries(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ec.time, "sleep", sleeps.append)
    resp = ec._send_with_retry(lambda: FakeResp(503), "GET /x")
    assert resp.status_code == 503          # final failure surfaces to caller
    assert len(sleeps) == ec.MAX_TRIES - 1  # backed off between tries
    assert sleeps == sorted(sleeps)         # waits grow


def test_non_retryable_errors_pass_through_immediately(monkeypatch):
    called = {"n": 0}

    def send():
        called["n"] += 1
        return FakeResp(404)

    resp = ec._send_with_retry(send, "GET /x")
    assert resp.status_code == 404
    assert called["n"] == 1
