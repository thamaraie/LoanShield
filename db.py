from collections.abc import Iterable

import duckdb

from schemas import Verdict


def open_database(path: str) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(path)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS verdicts (
            loan_id TEXT PRIMARY KEY,
            rule1_pass BOOLEAN NOT NULL,
            rule2_pass BOOLEAN NOT NULL,
            rule3_pass BOOLEAN NOT NULL,
            fx_rate_used REAL,
            fx_fetched_at TEXT,
            degraded BOOLEAN NOT NULL,
            policy_version TEXT NOT NULL
        )"""
    )
    return connection


def save_verdicts(connection: duckdb.DuckDBPyConnection, verdicts: Iterable[Verdict]) -> None:
    connection.executemany(
        """INSERT OR REPLACE INTO verdicts VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                verdict.loan_id,
                verdict.rule1_pass,
                verdict.rule2_pass,
                verdict.rule3_pass,
                verdict.fx_rate_used,
                verdict.fx_fetched_at,
                verdict.degraded,
                verdict.policy_version,
            )
            for verdict in verdicts
        ],
    )
    connection.commit()