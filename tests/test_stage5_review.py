"""Stage 5 tests against a synthetic DB matching the real Stage 1-4 schema."""
from __future__ import annotations

import duckdb
import pytest

from src.api import review


@pytest.fixture
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "loanguard.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute(
        """
        CREATE TABLE enriched_loans (
            loan_id VARCHAR, company_name VARCHAR, hq_country VARCHAR,
            asset_description VARCHAR, asset_value DOUBLE, asset_owner VARCHAR,
            loan_value DOUBLE, loan_currency VARCHAR,
            loan_value_eur DOUBLE, expected_currency VARCHAR,
            fx_rate_used DOUBLE, fx_fetched_at VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE verdicts (
            loan_id VARCHAR PRIMARY KEY, rule1_pass BOOLEAN, rule2_pass BOOLEAN,
            rule3_pass BOOLEAN, fx_rate_used DOUBLE, fx_fetched_at VARCHAR,
            degraded BOOLEAN, policy_version VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE suggestions (
            loan_id VARCHAR PRIMARY KEY, rule INTEGER, action VARCHAR,
            explanation VARCHAR, source_page INTEGER, asset_name VARCHAR,
            verified BOOLEAN, cache_hit BOOLEAN
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE companies (
            company_id VARCHAR, name VARCHAR, assets JSON
        )
        """
    )
    connection.execute("CREATE SEQUENCE review_actions_id_seq START 1")
    connection.execute(
        """
        CREATE TABLE review_actions (
            id INTEGER PRIMARY KEY, loan_id TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('manual_fix', 'ignore', 'accept_ai')),
            payload JSON, actor TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
        )
        """
    )

    connection.execute(
        "INSERT INTO enriched_loans VALUES "
        "('L1','Acme','USA','Widget',1000,'Acme',30000,'USD',27000,'EUR',0.9,'2026-01-01'),"
        "('L2','Acme','USA','Gadget',2000,'Acme',10000,'EUR',10000,'EUR',1.0,'2026-01-01')"
    )
    connection.execute(
        "INSERT INTO verdicts VALUES "
        "('L1', true, false, true, 0.9, '2026-01-01', false, 'stage3-v1'),"
        "('L2', false, true, true, 1.0, '2026-01-01', false, 'stage3-v1')"
    )
    connection.execute(
        "INSERT INTO suggestions VALUES "
        "('L1', 2, 'change_currency', 'Change to EUR', NULL, NULL, true, false)"
    )
    connection.execute(
        """INSERT INTO companies VALUES
        ('C1', 'Acme', '[{"name": "Warehouse", "value": 5000, "currency": "EUR"}]')"""
    )

    monkeypatch.setattr(
        review, "revalidate_loan",
        lambda loan: {"rule1_pass": True, "rule2_pass": True, "rule3_pass": True},
    )
    yield connection
    connection.close()


def test_list_failures_returns_only_failing_rows(conn):
    rows, next_cursor = review.list_failures(conn, None, None, None, 100)
    assert {row["loan_id"] for row in rows} == {"L1", "L2"}
    assert next_cursor is None


def test_list_failures_filters_by_rule(conn):
    rows, _ = review.list_failures(conn, 2, None, None, 100)
    assert [row["loan_id"] for row in rows] == ["L1"]


def test_list_failures_pagination_cursor(conn):
    rows, next_cursor = review.list_failures(conn, None, None, None, 1)
    assert [row["loan_id"] for row in rows] == ["L1"]
    assert next_cursor == "L1"
    rows2, next_cursor2 = review.list_failures(conn, None, None, next_cursor, 1)
    assert [row["loan_id"] for row in rows2] == ["L2"]
    assert next_cursor2 is None


def test_report_contains_rule_counts_company_totals_and_unresolved(conn):
    report = review.get_report(conn)

    assert report["total_checked"] == 2
    assert report["rule1_failures"] == 1
    assert report["rule2_failures"] == 1
    assert report["rule3_failures"] == 0
    assert report["failed_any"] == 2
    assert report["review_status"] == {
        "manual_fix": 0,
        "accept_ai": 0,
        "ignore": 0,
        "unresolved": 2,
        "still_failing": 0,
    }
    assert report["per_company"] == [{"company_name": "Acme", "loan_value_eur": 37000.0}]


def test_get_suggestion_found_and_missing(conn):
    suggestion = review.get_suggestion(conn, "L1")
    assert suggestion["action"] == "change_currency"
    with pytest.raises(review.NotFoundError):
        review.get_suggestion(conn, "L2")


def test_record_action_ignore_is_logged_without_revalidation(conn):
    result = review.record_action(conn, "L2", "ignore", {}, actor="reviewer1")
    assert result["still_failing"] is None
    assert result["action"] == "ignore"


def test_record_action_manual_fix_revalidates_and_reports_still_failing(conn):
    result = review.record_action(
        conn, "L2", "manual_fix", {"edits": {"loan_value_eur": 30000}}, actor="reviewer1"
    )
    assert result["still_failing"] is False


def test_record_action_accept_ai_uses_suggestion(conn):
    result = review.record_action(conn, "L1", "accept_ai", {}, actor="reviewer1")
    assert result["still_failing"] is False
