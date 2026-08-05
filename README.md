# LoanShield

Stage 3 loan compliance evaluator. The pipeline loads loan records, evaluates
three deterministic policy rules, validates the results, and stores verdicts in
DuckDB.

## Project Layout

```text
stage3/
├── main.py                    # CLI entry point and batch orchestration
├── schemas.py                 # Loan and Verdict data models
├── opa.py                     # Local evaluator and optional OPA client
├── review.py                  # Completeness and rule reconciliation checks
├── db.py                      # DuckDB schema and verdict persistence
├── loans.csv                  # Input loan records
├── policies/
│   └── compliance.rego        # OPA implementation of the three rules
├── requirements.txt           # Python dependencies
├── stage3.duckdb              # Generated verdict database
└── IMPLEMENTATION.md          # Detailed stage design and validation notes
```

## Rules

| Rule | Requirement |
| --- | --- |
| Rule 1 | `loan_value_eur` is greater than EUR 25,000 |
| Rule 2 | Loan currency matches the expected company currency |
| Rule 3 | Asset value is at least 50% of the loan value |

Rule 1 is strict at the threshold: exactly EUR 25,000 fails. Rule 3 is
inclusive: exactly 50% coverage passes.

## Run

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Evaluate the sample input using the local evaluator:

```powershell
python main.py --input loans.csv --db stage3.duckdb --batch-size 1000
```

The command prints a JSON summary and writes verdicts to the `verdicts` table.

To evaluate through a running OPA server instead, pass its base URL:

```powershell
python main.py --input loans.csv --db stage3.duckdb --opa-url http://localhost:8181
```

OPA must have `policies/` mounted and expose the `compliance/decisions` query.

## Output

Each verdict stores the three rule outcomes, policy version, and FX metadata:

```text
loan_id | rule1_pass | rule2_pass | rule3_pass | fx_rate_used | fx_fetched_at | degraded | policy_version
```

The source CSV is read-only; repeated runs replace verdicts by `loan_id`.
Bil-LoanShield
 
