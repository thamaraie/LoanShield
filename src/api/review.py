"""Stage 5 business logic: paged failures, suggestions, and the review action log.

Expected upstream tables (produced by stages 1-4, read-only from here):
  enriched_loans(loan_id, company_name, hq_country, asset_description, asset_owner,
                 loan_value, loan_value_eur, loan_currency, expected_currency, asset_value,
                 fx_rate_used, fx_fetched_at)
  verdicts(loan_id, rule1_pass, rule2_pass, rule3_pass, fx_rate_used,
           fx_fetched_at, degraded, policy_version)
  suggestions(loan_id, rule, action, explanation, source_page, asset_name,
              verified, cache_hit)
"""
from __future__ import annotations

import json
from typing import Any, Optional

import duckdb

from src.api.opa import revalidate_loan

MAX_LIMIT = 100


class NotFoundError(Exception):
    pass


def _fetch_records(result: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [column[0] for column in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def get_report(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Return aggregate verdict and review data without loading loan rows."""
    totals = conn.execute(
        """
        SELECT
            count(*) AS total_checked,
            count(*) FILTER (WHERE NOT rule1_pass) AS rule1_failures,
            count(*) FILTER (WHERE NOT rule2_pass) AS rule2_failures,
            count(*) FILTER (WHERE NOT rule3_pass) AS rule3_failures,
            count(*) FILTER (WHERE NOT (rule1_pass AND rule2_pass AND rule3_pass)) AS failed_any,
            max(fx_fetched_at) AS fx_fetched_at,
            bool_or(degraded) AS fx_degraded,
            max(policy_version) AS policy_version
        FROM verdicts
        """
    ).fetchone()
    status_rows = conn.execute(
        """
        WITH latest AS (
            SELECT action, payload,
                   row_number() OVER (PARTITION BY loan_id ORDER BY created_at DESC, id DESC) AS rn
            FROM review_actions
        )
        SELECT
            count(*) FILTER (WHERE rn = 1 AND action = 'manual_fix') AS manual_fix,
            count(*) FILTER (WHERE rn = 1 AND action = 'accept_ai') AS accept_ai,
            count(*) FILTER (WHERE rn = 1 AND action = 'ignore') AS ignore,
            count(*) FILTER (WHERE rn = 1 AND action IN ('manual_fix', 'accept_ai') AND (
                json_extract_string(payload, '$.revalidation.rule1_pass') = 'false'
                OR json_extract_string(payload, '$.revalidation.rule2_pass') = 'false'
                OR json_extract_string(payload, '$.revalidation.rule3_pass') = 'false'
            )) AS still_failing
        FROM latest
        WHERE rn = 1
        """
    ).fetchone()
    companies = _fetch_records(conn.execute(
        """
        SELECT company_name, sum(loan_value_eur) AS loan_value_eur
        FROM enriched_loans
        GROUP BY company_name
        ORDER BY company_name
        """
    ))

    total_checked = totals[0] or 0
    reviewed = sum(value or 0 for value in status_rows[:3])
    return {
        "total_checked": total_checked,
        "rule1_failures": totals[1] or 0,
        "rule2_failures": totals[2] or 0,
        "rule3_failures": totals[3] or 0,
        "failed_any": totals[4] or 0,
        "review_status": {
            "manual_fix": status_rows[0] or 0,
            "accept_ai": status_rows[1] or 0,
            "ignore": status_rows[2] or 0,
            "unresolved": max(total_checked - reviewed, 0),
            "still_failing": status_rows[3] or 0,
        },
        "per_company": companies,
        "run": {
            "timestamp": totals[5],
            "fx_rates": {},
            "fx_degraded": bool(totals[6]) if totals[6] is not None else False,
            "policy_version": totals[7],
        },
    }


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
        where.append("el.company_name = ?")
        params.append(company)

    if cursor:
        where.append("v.loan_id > ?")
        params.append(cursor)

    sql = f"""
        SELECT
            v.loan_id, el.company_name, el.hq_country,
            el.asset_description, el.asset_owner,
            el.loan_value, el.loan_value_eur, el.loan_currency,
            el.expected_currency, el.asset_value,
            v.rule1_pass, v.rule2_pass, v.rule3_pass,
            v.fx_rate_used, v.fx_fetched_at, v.degraded, v.policy_version,
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

    rows = _fetch_records(conn.execute(sql, params))

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1]["loan_id"]

    return rows, next_cursor


def get_suggestion(conn: duckdb.DuckDBPyConnection, loan_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT loan_id, rule, action, explanation, source_page, asset_name,
               verified, cache_hit
        FROM suggestions
        WHERE loan_id = ?
        """,
        [loan_id],
    ).fetchone()
    if row is None:
        raise NotFoundError(f"no suggestion for loan_id={loan_id}")

    loan_id_, rule, action, explanation, source_page, asset_name, verified, cache_hit = row
    return {
        "loan_id": loan_id_,
        "rule": rule,
        "action": action,
        "explanation": explanation,
        "source_page": source_page,
        "asset_name": asset_name,
        "verified": verified,
        "cache_hit": cache_hit,
    }


def _get_enriched_loan(conn: duckdb.DuckDBPyConnection, loan_id: str) -> dict[str, Any]:
    result = conn.execute(
        "SELECT * FROM enriched_loans WHERE loan_id = ?", [loan_id]
    )
    rows = _fetch_records(result)
    if not rows:
        raise NotFoundError(f"no loan for loan_id={loan_id}")
    return rows[0]


def _asset_value(conn: duckdb.DuckDBPyConnection, company_name: str, asset_name: str) -> float:
    """Looks up a named asset's value from the company's profile (Stage 1's `companies` table)."""
    row = conn.execute(
        "SELECT assets FROM companies WHERE name = ?", [company_name]
    ).fetchone()
    if row is None:
        raise NotFoundError(f"no company profile for {company_name}")
    assets = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    for asset in assets:
        if asset["name"] == asset_name:
            return asset["value"]
    raise NotFoundError(f"asset {asset_name} not found for {company_name}")


def _edits_for_accept_ai(conn: duckdb.DuckDBPyConnection, loan: dict[str, Any], suggestion: dict[str, Any]) -> dict[str, Any]:
    """Mirrors Stage 4's own correction so the same suggestion re-validates the same way."""
    edits: dict[str, Any] = {}
    if suggestion["action"] in ("change_currency", "change_currency_and_asset"):
        edits["loan_currency"] = loan["expected_currency"]
    if suggestion["action"] in ("change_currency_and_asset", "substitute_asset"):
        edits["asset_value"] = _asset_value(conn, loan["company_name"], suggestion["asset_name"])
    return edits


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
        if action == "manual_fix":
            edits = payload.get("edits", {})
        else:
            edits = _edits_for_accept_ai(conn, loan, get_suggestion(conn, loan_id))
        candidate = {**loan, **edits}
        decision = revalidate_loan(candidate)
        payload = {**payload, "edits": edits, "revalidation": decision}
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
