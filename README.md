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

## Running the Suggestion Agent

Generate suggestions:

```bash
python scripts/run_suggestions.py
```

Evaluate the Rule 3 golden set:

```bash
python scripts/evaluate_golden_set.py
```

Run tests:

```bash
pytest tests
```

## Stage 4 Deliverables

- Suggestion generation for failed compliance rules.
- Rule 3 asset recommendation engine.
- OPA revalidation of generated suggestions.
- Suggestion caching mechanism.
- Golden set evaluation for retrieval accuracy.
- Automated test suite.

## Commit

```
Stage 4: Implement Suggestion Agent
```