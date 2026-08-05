# LoanShield – Stage 4: Suggestion Agent

## Overview

This stage implements the **Suggestion Agent** for LoanShield. After loan applications are evaluated against compliance policies, the Suggestion Agent generates corrective recommendations for failed loans to help reviewers resolve compliance issues efficiently.

## Features

- Rule-based suggestion generation for failed loan applications.
- Deterministic suggestion routing based on the failed compliance rule.
- Rule 3 asset retrieval using Retrieval-Augmented Generation (RAG).
- OPA (Open Policy Agent) revalidation of generated suggestions.
- Suggestion caching for improved performance.
- Golden set evaluation for validating Rule 3 asset recommendations.

## Project Structure

```
src/
├── suggestions.py      # Suggestion generation engine
├── rag.py              # Asset retrieval and explanation logic
├── evaluate.py         # OPA revalidation support
└── __init__.py

scripts/
├── run_suggestions.py      # Runs Stage 4 suggestion generation
└── evaluate_golden_set.py  # Evaluates Rule 3 golden dataset

tests/
├── conftest.py
└── test_suggestions.py
```

## Stage 4 Deliverables

- Suggestion generation for failed compliance rules.
- Rule 3 asset recommendation engine.
- OPA revalidation of generated suggestions.
- Suggestion caching mechanism.
- Golden set evaluation for retrieval accuracy.
- Automated test suite.
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
 
