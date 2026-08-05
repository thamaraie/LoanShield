import csv
import json
from datetime import datetime, timezone

import duckdb

from src.ingest.enrich import enrich_database
from src.ingest.load_loans import load_database


def test_enrichment_preserves_raw_loans_and_writes_auditable_outputs(tmp_path):
    profiles_path = tmp_path / "companies.json"
    profiles_path.write_text(
        json.dumps(
            [
                {
                    "company_id": "C001",
                    "name": "Example",
                    "hq_country": "Germany",
                    "industry": "Industry",
                    "assets": [],
                    "related_entities": [],
                    "source_page": 1,
                    "raw_text": "raw",
                }
            ]
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "loans.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "loan_id",
                "company_name",
                "hq_country",
                "asset_description",
                "asset_value",
                "asset_owner",
                "loan_value",
                "loan_currency",
            ]
        )
        writer.writerow(["L000001", "Example", "Germany", "Asset", 1000, "Example", 2000, "USD"])

    database_path = tmp_path / "loans.duckdb"
    load_database(csv_path, profiles_path, database_path)
    fetched_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    count = enrich_database(
        database_path,
        {"USD": 2},
        fetched_at,
        True,
        tmp_path / "enriched_loans.json",
    )

    with duckdb.connect(str(database_path)) as connection:
        assert count == 1
        assert connection.execute("SELECT COUNT(*) FROM loans").fetchone()[0] == 1
        assert connection.execute("SELECT loan_value, loan_currency FROM loans").fetchone() == (2000, "USD")
        enriched = connection.execute(
            "SELECT loan_value_eur, expected_currency, fx_rate_used FROM enriched_loans"
        ).fetchone()
        assert enriched == (1000, "EUR", 2)

    output = json.loads((tmp_path / "enriched_loans.json").read_text(encoding="utf-8"))
    assert output["metadata"] == {
        "fx_fetched_at": "2026-08-02T00:00:00+00:00",
        "fx_degraded": True,
        "row_count": 1,
    }
    assert output["loans"][0]["loan_value_eur"] == 1000
