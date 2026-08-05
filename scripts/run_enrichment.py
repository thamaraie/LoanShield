"""Fetch FX rates and run the Stage 2 loan enrichment."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest.enrich import enrich_database
from src.ingest.fx import fetch_rates


if __name__ == "__main__":
    rates, fetched_at, degraded = fetch_rates(Path("data/fx_cache.json"))
    count = enrich_database(
        Path("data/loanguard.duckdb"),
        rates,
        fetched_at,
        degraded,
        Path("data/enriched_loans.json"),
    )
    mode = "degraded cache" if degraded else "live FX"
    print(f"Enriched {count} loans using {mode}")
