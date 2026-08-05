"""Measure deterministic Rule 3 retrieval against the checked-in sample set."""

import json
from pathlib import Path

import duckdb


DATABASE = Path("data/loanguard.duckdb")
GOLDEN_SET = Path("data/golden_set_rule3.json")


def evaluate(database_path: Path = DATABASE, golden_path: Path = GOLDEN_SET) -> float:
    """Return the fraction of golden-set expected assets retrieved exactly."""
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    with duckdb.connect(str(database_path), read_only=True) as connection:
        actual = dict(
            connection.execute(
                "SELECT loan_id, asset_name FROM suggestions WHERE loan_id IN (SELECT UNNEST(?))",
                [[case["loan_id"] for case in cases]],
            ).fetchall()
        )

    correct = sum(actual.get(case["loan_id"]) == case["expected_asset"] for case in cases)
    accuracy = correct / len(cases)
    print(f"Rule 3 golden set: {correct}/{len(cases)} correct ({accuracy:.1%})")
    return accuracy


if __name__ == "__main__":
    evaluate()
