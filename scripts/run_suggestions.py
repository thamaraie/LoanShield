"""Generate and store verified suggestions for failed verdicts."""

import sys
from pathlib import Path

import duckdb
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag import AssetRag, ChromaAssetStore
from src.suggestions import SuggestionCache, load_profiles, suggest_cached


DATABASE = Path("data/loanguard.duckdb")
PROFILES = Path("data/companies.json")
OPA_URL = "http://127.0.0.1:8181"


def run(database_path: Path = DATABASE) -> dict[str, int | float]:
    """Generate suggestions for every failed verdict and persist them."""
    profiles = load_profiles(PROFILES)
    rag = AssetRag(ChromaAssetStore())
    rag.store.index_profiles(profiles)
    cache = SuggestionCache()
    rows_written = 0
    rule_counts = {1: 0, 2: 0, 3: 0}

    with duckdb.connect(str(database_path)) as connection, httpx.Client(timeout=30) as client:
        rows = connection.execute(
            """
            SELECT e.*, v.rule1_pass, v.rule2_pass, v.rule3_pass
            FROM enriched_loans AS e
            JOIN verdicts AS v ON v.loan_id = e.loan_id
            WHERE NOT (v.rule1_pass AND v.rule2_pass AND v.rule3_pass)
            ORDER BY e.loan_id
            """
        ).fetchall()
        columns = [item[0] for item in connection.description]
        connection.execute("DROP TABLE IF EXISTS suggestions")
        connection.execute(
            """
            CREATE TABLE suggestions (
                loan_id VARCHAR PRIMARY KEY,
                rule INTEGER NOT NULL,
                action VARCHAR NOT NULL,
                explanation VARCHAR NOT NULL,
                source_page INTEGER,
                asset_name VARCHAR,
                verified BOOLEAN NOT NULL,
                cache_hit BOOLEAN NOT NULL
            )
            """
        )

        values = []
        for row in rows:
            record = dict(zip(columns, row))
            verdict = {f"rule{rule}_pass": record.pop(f"rule{rule}_pass") for rule in (1, 2, 3)}
            suggestion, cache_hit = suggest_cached(
                record, verdict, profiles, cache, client, OPA_URL, rag
            )
            rule_counts[suggestion.rule] += 1
            values.append(
                (
                    suggestion.loan_id,
                    suggestion.rule,
                    suggestion.action,
                    suggestion.explanation,
                    suggestion.source_page,
                    suggestion.asset_name,
                    suggestion.verified,
                    cache_hit,
                )
            )

        connection.executemany("INSERT INTO suggestions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
        rows_written = len(values)

    unverified_actionable = [
        value for value in values if not value[6] and value[2] != "no_qualifying_asset"
    ]
    if unverified_actionable:
        raise RuntimeError(
            f"{len(unverified_actionable)} actionable suggestions failed OPA revalidation"
        )

    total_requests = cache.hits + cache.misses
    hit_rate = cache.hits / total_requests if total_requests else 0.0
    metrics = {
        "suggestions": rows_written,
        "rule1": rule_counts[1],
        "rule2": rule_counts[2],
        "rule3": rule_counts[3],
        "cache_hits": cache.hits,
        "cache_misses": cache.misses,
        "cache_hit_rate": hit_rate,
        "opa_calls": cache.opa_calls,
    }
    print(
        f"Suggestions: {rows_written}; Rule 1/2/3: "
        f"{rule_counts[1]}/{rule_counts[2]}/{rule_counts[3]}"
    )
    print(
        f"Cache hits/misses: {cache.hits}/{cache.misses} "
        f"({hit_rate:.1%}); OPA revalidations: {cache.opa_calls}"
    )
    return metrics


if __name__ == "__main__":
    run()
