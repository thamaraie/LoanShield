"""Stage 5 business logic: paged failures, suggestions, and the review action log.

Expected upstream tables (produced by stages 1-4, read-only from here):
  enriched_loans(loan_id, company_id, company_name, loan_value, loan_value_eur,
                 loan_currency, expected_currency, asset_value, ...)
  verdicts(loan_id, rule1_pass, rule2_pass, rule3_pass, fx_rate_used,
           fx_fetched_at, policy_version)
  suggestions(loan_id, rule, suggestion_type, detail JSON, revalidated)
"""
from __future__ import annotations

import json
from typing import Any, Optional

import duckdb

from src.api.opa import revalidate_loan

MAX_LIMIT = 100


class NotFoundError(Exception):
    pass


def list_failures(
    conn: duckdb.DuckDBPyConnection,
    rule: Optional[int],
    company: Optional[str],
    cursor: Optional[str],
    limit: int,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Keyset-paginated page of failing rows, newest verdict per loan, failures only."""
    limit = min(limit, MAX_LIMIT)

    if rule is not None and rule not in (1, 2, 3):
        raise ValueError("rule must be 1, 2 or 3")

    where = [f"NOT v.rule{rule}_pass"] if rule else [
        "NOT (v.rule1_pass AND v.rule2_pass AND v.rule3_pass)"
    ]
    params: list[Any] = []

    if company:
        where.append("(el.company_id = ? OR el.company_name = ?)")
        params.extend([company, company])

    if cursor:
        where.append("v.loan_id > ?")
        params.append(cursor)

    sql = f"""
        SELECT
            v.loan_id, el.company_id, el.company_name,
            el.loan_value, el.loan_value_eur, el.loan_currency,
            el.expected_currency, el.asset_value,
            v.rule1_pass, v.rule2_pass, v.rule3_pass,
            v.fx_rate_used, v.fx_fetched_at, v.policy_version,
            latest.action AS current_state
        FROM verdicts v
        JOIN enriched_loans el ON el.loan_id = v.loan_id
        LEFT JOIN (
            SELECT loan_id, action,
                   row_number() OVER (PARTITION BY loan_id ORDER BY created_at DESC) AS rn
            FROM review_actions
        ) latest ON latest.loan_id = v.loan_id AND latest.rn = 1
        WHERE {' AND '.join(where)}
        ORDER BY v.loan_id
        LIMIT ?
    """
    params.append(limit + 1)

    rows = conn.execute(sql, params).fetchdf().to_dict(orient="records")

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1]["loan_id"]

    return rows, next_cursor


def get_suggestion(conn: duckdb.DuckDBPyConnection, loan_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT loan_id, rule, suggestion_type, detail, revalidated
        FROM suggestions
        WHERE loan_id = ?
        """,
        [loan_id],
    ).fetchone()
    if row is None:
        raise NotFoundError(f"no suggestion for loan_id={loan_id}")

    loan_id_, rule, suggestion_type, detail, revalidated = row
    if isinstance(detail, str):
        detail = json.loads(detail)
    return {
        "loan_id": loan_id_,
        "rule": rule,
        "suggestion_type": suggestion_type,
        "detail": detail,
        "revalidated": revalidated,
        "source": "cache",
    }


def _get_enriched_loan(conn: duckdb.DuckDBPyConnection, loan_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM enriched_loans WHERE loan_id = ?", [loan_id]
    ).fetchdf()
    if row.empty:
        raise NotFoundError(f"no loan for loan_id={loan_id}")
    return row.to_dict(orient="records")[0]


def record_action(
    conn: duckdb.DuckDBPyConnection,
    loan_id: str,
    action: str,
    payload: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    """Appends the action to the log and, for fixes, re-validates through OPA.

    Never updates loans/verdicts in place — current state is always derived
    from the latest row in review_actions.
    """
    still_failing = None

    if action in ("manual_fix", "accept_ai"):
        loan = _get_enriched_loan(conn, loan_id)
        edits = payload.get("edits", {})
        candidate = {**loan, **edits}
        decision = revalidate_loan(candidate)
        payload = {**payload, "revalidation": decision}
        still_failing = not (
            decision["rule1_pass"] and decision["rule2_pass"] and decision["rule3_pass"]
        )

    result = conn.execute(
        """
        INSERT INTO review_actions (id, loan_id, action, payload, actor)
        VALUES (nextval('review_actions_id_seq'), ?, ?, ?, ?)
        RETURNING id, loan_id, action, created_at
        """,
        [loan_id, action, json.dumps(payload), actor],
    ).fetchone()

    return {
        "loan_id": result[1],
        "action": result[2],
        "created_at": result[3],
        "still_failing": still_failing,
    }
