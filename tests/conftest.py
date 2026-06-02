import importlib

import pytest


@pytest.fixture(autouse=True)
def fresh_env(tmp_path, monkeypatch):
    """各テストで独立した一時DBと mock データソースを使う。"""
    from app import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "MARKET_DATA_SOURCE", "mock")
    monkeypatch.setattr(config, "MARKET_FALLBACK_TO_MOCK", True)
    monkeypatch.setattr(config, "STARTING_CASH", 1_000_000.0)

    from app import database

    database.init_db()
    yield
