from dataclasses import dataclass
from typing import Any


COUNTRY_CURRENCY = {
    "Germany": "EUR", "Ireland": "EUR", "Spain": "EUR", "France": "EUR",
    "Italy": "EUR", "Netherlands": "EUR", "Portugal": "EUR", "Belgium": "EUR",
    "Austria": "EUR", "Finland": "EUR", "Luxembourg": "EUR",
    "United Kingdom": "GBP", "United States": "USD", "Switzerland": "CHF",
    "Sweden": "SEK", "Canada": "CAD", "Poland": "PLN", "Japan": "JPY",
}


@dataclass(frozen=True)
class Loan:
    loan_id: str
    loan_value: float
    loan_value_eur: float
    loan_currency: str
    expected_currency: str
    asset_value: float
    fx_rate_used: float | None = None
    fx_fetched_at: str | None = None
    degraded: bool = False

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "Loan":
        expected_currency = row.get("expected_currency")
        if not expected_currency:
            expected_currency = COUNTRY_CURRENCY[row["hq_country"]]
        return cls(
            loan_id=row["loan_id"],
            loan_value=float(row["loan_value"]),
            loan_value_eur=float(row.get("loan_value_eur", row["loan_value"])),
            loan_currency=row["loan_currency"],
            expected_currency=expected_currency,
            asset_value=float(row["asset_value"]),
            fx_rate_used=float(row["fx_rate_used"]) if row.get("fx_rate_used") else None,
            fx_fetched_at=row.get("fx_fetched_at"),
            degraded=bool(row.get("degraded", False)),
        )


@dataclass(frozen=True)
class Verdict:
    loan_id: str
    rule1_pass: bool
    rule2_pass: bool
    rule3_pass: bool
    fx_rate_used: float | None
    fx_fetched_at: str | None
    degraded: bool
    policy_version: str = "stage3-v1"
