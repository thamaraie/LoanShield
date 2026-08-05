from datetime import datetime, timedelta, timezone
import json

import pytest

from src.ingest import fx


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def rates():
    return {currency: 2 for currency in fx.REQUIRED_CURRENCIES if currency != "EUR"}


def test_fetch_rates_calls_api_once_and_caches(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        fx.httpx,
        "get",
        lambda *args, **kwargs: (calls.append((args, kwargs)) or Response({"rates": rates()})),
    )

    fetched_rates, fetched_at, degraded = fx.fetch_rates(tmp_path / "fx_cache.json")

    assert len(calls) == 1
    assert fetched_rates["USD"] == 2
    assert fetched_at.tzinfo is not None
    assert degraded is False
    assert json.loads((tmp_path / "fx_cache.json").read_text())["rates"]["USD"] == 2


def test_fetch_rates_uses_fresh_cache_on_network_failure(tmp_path, monkeypatch):
    fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
    cache = tmp_path / "fx_cache.json"
    fx.save_cache(cache, rates(), fetched_at)
    monkeypatch.setattr(fx.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))

    _, actual_fetched_at, degraded = fx.fetch_rates(cache)

    assert actual_fetched_at == fetched_at
    assert degraded is True


def test_fetch_rates_rejects_stale_cache(tmp_path, monkeypatch):
    cache = tmp_path / "fx_cache.json"
    fx.save_cache(cache, rates(), datetime.now(timezone.utc) - timedelta(hours=25))
    monkeypatch.setattr(fx.httpx, "get", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))

    with pytest.raises(fx.FxUnavailable, match="older than 24 hours"):
        fx.fetch_rates(cache)


def test_to_eur_divides_eur_base_rate():
    assert fx.to_eur(100, "USD", {"USD": 2}) == 50
    assert fx.to_eur(100, "EUR", {}) == 100
