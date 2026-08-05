"""OPA client used to re-validate a single edited loan row (manual fix / accept-ai)."""
from __future__ import annotations

import os
from typing import Any

import httpx

OPA_URL = os.environ.get("OPA_URL", "http://localhost:8181")
DECISION_PATH = "/v1/data/compliance/decisions"


def revalidate_loan(loan: dict[str, Any]) -> dict[str, bool]:
    """Runs a single loan through the same policy path as the full batch evaluation.

    Returns the rule1/rule2/rule3 pass booleans for the (possibly edited) row.
    Raises httpx.HTTPError if OPA is unreachable or returns a non-2xx status —
    a manual fix must never be silently accepted without a real re-check.
    """
    resp = httpx.post(
        f"{OPA_URL}{DECISION_PATH}",
        json={"input": {"loans": [loan]}},
        timeout=10,
    )
    resp.raise_for_status()
    decisions = resp.json()["result"]
    return decisions[0]
