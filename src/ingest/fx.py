"""Fetch and cache the single FX snapshot used by enrichment."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import ssl
from typing import Any

import httpx
import truststore


FX_URL = "https://api.frankfurter.dev/v1/latest"
MAX_CACHE_AGE = timedelta(hours=24)
REQUIRED_CURRENCIES = {"CHF", "USD", "GBP", "SEK", "CAD", "PLN", "JPY"}
TLS_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class FxUnavailable(RuntimeError):
    """Raised when no current or acceptable cached FX snapshot is available."""


def now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def _timestamp(value: str) -> datetime:
    """Parse an ISO timestamp and normalize it to UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_rates(rates: dict[str, Any]) -> dict[str, float]:
    """Return numeric rates when every loan currency is available."""
    missing = REQUIRED_CURRENCIES - set(rates)
    if missing:
        raise FxUnavailable(f"FX response is missing rates: {sorted(missing)}")
    try:
        return {currency: float(rates[currency]) for currency in REQUIRED_CURRENCIES}
    except (TypeError, ValueError) as exc:
        raise FxUnavailable("FX response contains a non-numeric rate") from exc


def save_cache(cache_path: Path, rates: dict[str, float], fetched_at: datetime) -> None:
    """Save rates and their retrieval timestamp for outage fallback."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"rates": rates, "fetched_at": fetched_at.astimezone(timezone.utc).isoformat()},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_cache(cache_path: Path) -> tuple[dict[str, float], datetime]:
    """Load and validate a cached FX snapshot."""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        rates = _validate_rates(payload["rates"])
        fetched_at = _timestamp(payload["fetched_at"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FxUnavailable(f"Invalid or missing FX cache: {cache_path}") from exc
    return rates, fetched_at


def fetch_rates(
    cache_path: Path = Path("data/fx_cache.json"),
) -> tuple[dict[str, float], datetime, bool]:
    """Fetch EUR-based rates once, falling back to a cache no older than 24 hours."""
    try:
        response = httpx.get(
            FX_URL,
            params={"base": "EUR"},
            timeout=10,
            verify=TLS_CONTEXT,
        )
        response.raise_for_status()
        payload = response.json()
        rates = _validate_rates(payload["rates"])
        fetched_at = now_utc()
        save_cache(cache_path, rates, fetched_at)
        return rates, fetched_at, False
    except Exception as exc:
        try:
            rates, fetched_at = load_cache(cache_path)
        except FxUnavailable:
            raise FxUnavailable("FX API failed and no usable cache exists") from exc
        if now_utc() - fetched_at > MAX_CACHE_AGE:
            raise FxUnavailable("Cached FX rates are older than 24 hours") from exc
        return rates, fetched_at, True


def to_eur(value: float, currency: str, rates: dict[str, float]) -> float:
    """Convert a loan value to EUR using rates quoted from EUR."""
    if currency == "EUR":
        return float(value)
    if currency not in rates or rates[currency] <= 0:
        raise FxUnavailable(f"No positive EUR-based rate for {currency}")
    return float(value) / rates[currency]
