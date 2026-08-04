from collections.abc import Iterable

from schemas import Loan, Verdict


def check_results(loans: Iterable[Loan], verdicts: Iterable[Verdict]) -> None:
    loans = list(loans)
    verdicts = list(verdicts)
    assert len(loans) == len(verdicts), "one verdict is required per loan"
    assert len({verdict.loan_id for verdict in verdicts}) == len(verdicts), "duplicate loan_id"

    expected = {loan.loan_id: loan for loan in loans}
    for verdict in verdicts:
        loan = expected[verdict.loan_id]
        assert verdict.rule1_pass == (loan.loan_value_eur > 25_000)
        assert verdict.rule3_pass == (loan.asset_value >= 0.5 * loan.loan_value)