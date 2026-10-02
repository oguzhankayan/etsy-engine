"""Every test runs against a fresh, empty SQLite DB — never the real data/engine.db."""
import pytest

from etsy_engine import db
from etsy_engine.config import settings


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "engine.db")
    db.init_db()
