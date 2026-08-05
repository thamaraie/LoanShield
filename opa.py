import json
from urllib.request import Request, urlopen

from schemas import Loan, Verdict


POLICY_VERSION = "stage3-v1"
MIN_LOAN_EUR = 25_000
COVERAGE_RATIO = 0.5


def evaluate_locally(loans: list[Loan]) -> list[Verdict]:
    """Apply the same three rules as policies/compliance.rego."""
    return [
        Verdict(
            loan_id=loan.loan_id,
            rule1_pass=loan.loan_value_eur > MIN_LOAN_EUR,
            rule2_pass=loan.loan_currency == loan.expected_currency,
            rule3_pass=loan.asset_value >= COVERAGE_RATIO * loan.loan_value,
            fx_rate_used=loan.fx_rate_used,
            fx_fetched_at=loan.fx_fetched_at,
            degraded=loan.degraded,
        )
        for loan in loans
    ]


def evaluate_batch(loans: list[Loan], opa_url: str | None = None) -> list[Verdict]:
    """Evaluate one batch with OPA, or use the identical local evaluator."""
    if not opa_url:
        return evaluate_locally(loans)

    payload = json.dumps({"input": {"loans": [loan.__dict__ for loan in loans]}}).encode()
    request = Request(
        f"{opa_url.rstrip('/')}/v1/data/compliance/decisions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        decisions = json.load(response)["result"]

    by_id = {loan.loan_id: loan for loan in loans}
    return [
        Verdict(
            loan_id=decision["loan_id"],
            rule1_pass=decision["rule1_pass"],
            rule2_pass=decision["rule2_pass"],
            rule3_pass=decision["rule3_pass"],
            fx_rate_used=by_id[decision["loan_id"]].fx_rate_used,
            fx_fetched_at=by_id[decision["loan_id"]].fx_fetched_at,
            degraded=by_id[decision["loan_id"]].degraded,
        )
        for decision in decisions
    ]