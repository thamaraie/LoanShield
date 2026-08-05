"""Send enriched loan batches to OPA and persist its three verdicts."""

from pathlib import Path
from typing import Any

import duckdb
import httpx


POLICY_VERSION = "stage3-v1"
BATCH_SIZE = 1000


def _loan_rows(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Read only the fields required by the policy and audit metadata."""
    columns = [
        "loan_id",
        "loan_currency",
        "expected_currency",
        "loan_value",
        "loan_value_eur",
        "asset_value",
        "fx_rate_used",
        "fx_fetched_at",
    ]
    rows = connection.execute(f"SELECT {', '.join(columns)} FROM enriched_loans ORDER BY loan_id").fetchall()
    return [dict(zip(columns, row)) for row in rows]


def evaluate_batch(
    loans: list[dict[str, Any]],
    client: httpx.Client,
    opa_url: str,
) -> list[dict[str, Any]]:
    """Evaluate one batch and return OPA's ordered decisions."""
    response = client.post(
        f"{opa_url}/v1/data/compliance/decisions",
        json={"input": {"loans": loans}},
    )
    response.raise_for_status()
    decisions = response.json().get("result")
    if not isinstance(decisions, list) or len(decisions) != len(loans):
        raise RuntimeError("OPA returned an invalid decision batch")
    return decisions


def evaluate_database(
    database_path: Path,
    opa_url: str = "http://127.0.0.1:8181",
    batch_size: int = BATCH_SIZE,
) -> int:
    """Evaluate all enriched loans in batches and replace the verdicts table."""
    with duckdb.connect(str(database_path)) as connection:
        loans = _loan_rows(connection)
        connection.execute("DROP TABLE IF EXISTS verdicts")
        connection.execute(
            """
            CREATE TABLE verdicts (
                loan_id VARCHAR PRIMARY KEY,
                rule1_pass BOOLEAN NOT NULL,
                rule2_pass BOOLEAN NOT NULL,
                rule3_pass BOOLEAN NOT NULL,
                fx_rate_used DOUBLE NOT NULL,
                fx_fetched_at VARCHAR NOT NULL,
                policy_version VARCHAR NOT NULL
            )
            """
        )

        with httpx.Client(timeout=30) as client:
            for start in range(0, len(loans), batch_size):
                batch = loans[start : start + batch_size]
                decisions = evaluate_batch(batch, client, opa_url)
                values = [
                    (
                        decision["loan_id"],
                        decision["rule1_pass"],
                        decision["rule2_pass"],
                        decision["rule3_pass"],
                        loan["fx_rate_used"],
                        loan["fx_fetched_at"],
                        POLICY_VERSION,
                    )
                    for loan, decision in zip(batch, decisions)
                ]
                connection.executemany("INSERT INTO verdicts VALUES (?, ?, ?, ?, ?, ?, ?)", values)
                print(f"Evaluated {min(start + batch_size, len(loans))}/{len(loans)} loans", flush=True)

    return len(loans)
