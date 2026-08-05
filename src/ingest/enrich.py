"""Enrich raw loans with EUR values and auditable FX metadata."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import duckdb

from src.ingest.fx import to_eur
from src.reference.currencies import currency_for


def _json_value(value: Any) -> Any:
    """Convert DuckDB values into JSON-compatible values."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def enrich_database(
    database_path: Path,
    rates: dict[str, float],
    fetched_at: datetime,
    degraded: bool,
    json_path: Path,
) -> int:
    """Create enriched_loans and export its rows without changing loans."""
    with duckdb.connect(str(database_path)) as connection:
        connection.execute("DROP TABLE IF EXISTS enriched_loans")
        connection.execute("CREATE TABLE enriched_loans AS SELECT * FROM loans")
        connection.execute("ALTER TABLE enriched_loans ADD COLUMN loan_value_eur DOUBLE")
        connection.execute("ALTER TABLE enriched_loans ADD COLUMN expected_currency VARCHAR")
        connection.execute("ALTER TABLE enriched_loans ADD COLUMN fx_rate_used DOUBLE")
        connection.execute("ALTER TABLE enriched_loans ADD COLUMN fx_fetched_at VARCHAR")

        rows = connection.execute(
            "SELECT loan_id, hq_country, loan_value, loan_currency FROM loans"
        ).fetchall()
        updates = []
        for loan_id, hq_country, loan_value, loan_currency in rows:
            expected_currency = currency_for(hq_country)
            rate = 1.0 if loan_currency == "EUR" else rates[loan_currency]
            updates.append(
                (
                    to_eur(float(loan_value), loan_currency, rates),
                    expected_currency,
                    rate,
                    fetched_at.astimezone(timezone.utc).isoformat(),
                    loan_id,
                )
            )
        connection.execute(
            """
            CREATE TEMP TABLE enrichment_values (
                loan_value_eur DOUBLE,
                expected_currency VARCHAR,
                fx_rate_used DOUBLE,
                fx_fetched_at VARCHAR,
                loan_id VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO enrichment_values VALUES (?, ?, ?, ?, ?)",
            updates,
        )
        connection.execute(
            """
            UPDATE enriched_loans AS enriched
            SET loan_value_eur = values.loan_value_eur,
                expected_currency = values.expected_currency,
                fx_rate_used = values.fx_rate_used,
                fx_fetched_at = values.fx_fetched_at
            FROM enrichment_values AS values
            WHERE enriched.loan_id = values.loan_id
            """
        )
        columns = [item[0] for item in connection.execute("SELECT * FROM enriched_loans LIMIT 0").description]
        enriched_rows = [
            {column: _json_value(value) for column, value in zip(columns, row)}
            for row in connection.execute("SELECT * FROM enriched_loans ORDER BY loan_id").fetchall()
        ]

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "fx_fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
                    "fx_degraded": degraded,
                    "row_count": len(enriched_rows),
                },
                "loans": enriched_rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(enriched_rows)
