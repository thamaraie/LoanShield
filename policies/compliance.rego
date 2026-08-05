package compliance

import rego.v1

min_loan_eur := 25000
coverage_ratio := 0.5

decisions := [decision |
	loan := input.loans[_]
	decision := {
		"loan_id": loan.loan_id,
		"rule1_pass": loan.loan_value_eur > min_loan_eur,
		"rule2_pass": loan.loan_currency == loan.expected_currency,
		"rule3_pass": loan.asset_value >= coverage_ratio * loan.loan_value,
	}
]