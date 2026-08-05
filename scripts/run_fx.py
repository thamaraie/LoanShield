"""Fetch and cache the Stage 2 FX rate snapshot."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest.fx import fetch_rates


if __name__ == "__main__":
    rates, fetched_at, degraded = fetch_rates(Path("data/fx_cache.json"))
    mode = "degraded cache" if degraded else "live FX"
    print(f"Fetched {len(rates)} FX rates using {mode} (as of {fetched_at.isoformat()})")
