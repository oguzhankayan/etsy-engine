"""Optional print upscale: priced and asked before publishing, never redone, originals kept."""
import base64
import io
from decimal import Decimal

import pytest
from PIL import Image

from etsy_engine import __main__ as cli
from etsy_engine.generate import print_upscale
from etsy_engine.publish import publisher


def page(path, size=(1536, 2048), noise=False):
    im = Image.effect_noise(size, 60).convert("RGB") if noise else Image.new("RGB", size, "white")
    im.save(path, "JPEG", quality=90)
    return path


class Client:
    def __init__(self):
        self.runs, self.quotes = [], []

    def quote(self, model, inp):
        self.quotes.append((model, inp))
        return {"quote_id": "q", "credits": 7}

    def run(self, model, inp, timeout=300):
        self.runs.append((model, inp))
        source = Image.open(io.BytesIO(base64.b64decode(inp["image_url"].split(",", 1)[1])))
        buf = io.BytesIO()
        source.resize((source.width * 2, source.height * 2)).save(buf, "JPEG")
        return buf.getvalue()


@pytest.fixture
def product(tmp_path, monkeypatch):
    small = [page(tmp_path / "p1.jpg"), page(tmp_path / "p2.jpg")]
    big = page(tmp_path / "banner-1.jpg", size=(2480, 3508))
    other = tmp_path / "art.png"
    Image.new("RGB", (100, 100)).save(other)
    monkeypatch.setattr(publisher, "_page_groups", lambda pid: [("banner", [big]), ("Printables", small)])
    monkeypatch.setattr(publisher, "_asset_paths", lambda pid: small + [other])
    return small


def test_only_small_jpeg_pages_are_offered(product):
    assert print_upscale.pages_needing_upscale(1) == product


def test_pages_are_sent_at_full_size_within_the_request_budget(tmp_path):
    plain = page(tmp_path / "plain.jpg")
    uri = print_upscale.full_reference(plain)
    assert Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).size == (1536, 2048)
    busy = page(tmp_path / "busy.jpg", noise=True)
    uri = print_upscale.full_reference(busy, budget=400_000)
    assert len(uri) <= 400_000


def test_upscale_replaces_pages_keeps_originals_and_never_repeats(product):
    client = Client()
    assert print_upscale.estimate_usd(client, product) == Decimal("0.14") and len(client.quotes) == 1
    assert client.quotes[0][0] == "bria/increase-resolution" and client.quotes[0][1]["desired_increase"] == 2
    assert print_upscale.upscale(client, product, say=lambda line: None) == 2
    assert Image.open(product[0]).size == (3072, 4096)
    assert Image.open(product[0].with_name("p1.orig.jpg")).size == (1536, 2048)
    assert print_upscale.pages_needing_upscale(1) == []
    assert print_upscale.upscale(client, product, say=lambda line: None) == 0 and len(client.runs) == 2


def test_publish_asks_first_and_unattended_runs_never_spend(product, monkeypatch):
    client = Client()
    monkeypatch.setattr("etsy_engine.generate.raywake.RaywakeClient", lambda: client)
    monkeypatch.setattr("etsy_engine.generate.raywake.require_key", lambda: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.offer_print_upscale(1, None) == 0 and not client.quotes and not client.runs
    assert cli.offer_print_upscale(1, False) == 0
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("click.confirm", lambda *a, **k: False)
    assert cli.offer_print_upscale(1, None) == 0 and len(client.quotes) == 1 and not client.runs
    monkeypatch.setattr("click.confirm", lambda *a, **k: True)
    assert cli.offer_print_upscale(1, None) == 2 and len(client.runs) == 2


def test_an_explicit_flag_upscales_without_asking(product, monkeypatch):
    client = Client()
    monkeypatch.setattr("etsy_engine.generate.raywake.RaywakeClient", lambda: client)
    monkeypatch.setattr("etsy_engine.generate.raywake.require_key", lambda: None)
    monkeypatch.setattr("click.confirm", lambda *a, **k: pytest.fail("asked despite --upscale"))
    assert cli.offer_print_upscale(1, True) == 2 and not client.quotes
