"""DuckDB connection and the review_actions table this stage owns."""
from __future__ import annotations

from pathlib import Path

import duckdb

DB_PATH = "data/loanguard.duckdb"

_CREATE_REVIEW_ACTIONS = """
CREATE TABLE IF NOT EXISTS review_actions (
    id INTEGER PRIMARY KEY,
    loan_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('manual_fix', 'ignore', 'accept_ai')),
    payload JSON,
    actor TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

_CREATE_REVIEW_ACTIONS_SEQ = """
CREATE SEQUENCE IF NOT EXISTS review_actions_id_seq START 1;
"""


def get_connection(db_path: str = DB_PATH) -> duckdb.DuckDBPyConnection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(db_path)
    conn.execute(_CREATE_REVIEW_ACTIONS_SEQ)
    conn.execute(_CREATE_REVIEW_ACTIONS)
    return conn


def next_review_action_id(conn: duckdb.DuckDBPyConnection) -> int:
    return conn.execute("SELECT nextval('review_actions_id_seq')").fetchone()[0]
