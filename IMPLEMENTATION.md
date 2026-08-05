# Implementation Plan — Six Stages

Companion to `WORKFLOW.md`. Each stage below has a goal, the concrete artefacts
it produces, code where the detail matters, and a **Definition of Done** you can
check honestly before moving on.

One rule that overrides the schedule: a stage is not finished when it runs, it is
finished when someone who did *not* build it can explain it. Each stage has an
**Explain-it test** for exactly that.

---

## Stage 1 — Foundation and data layer

**Goal:** every input is loaded, validated and queryable. No rules yet, no LLM.

### Build

```
repo/
├── docker-compose.yml        # opa, api, ui
├── Makefile                  # make up / make ingest / make run / make test
├── data/
│   ├── companies.json        # generated, committed
│   └── fx_cache.json         # generated at runtime
├── src/
│   ├── ingest/pdf_profiles.py
│   ├── ingest/load_loans.py
│   └── reference/currencies.py
└── policies/                 # Rego lives here from stage 3
```

OPA as a service, so nobody is running a binary by hand on demo day:

```yaml
# docker-compose.yml
services:
  opa:
    image: openpolicyagent/opa:latest
    command: ["run","--server","--addr=0.0.0.0:8181","/policies"]
    volumes: ["./policies:/policies"]
    ports: ["8181:8181"]
```

**PDF → `companies.json`.** 104 pages: two index pages, then one profile per
company. Parse with pdfplumber, keyed off the `C0xx — Company Name` heading.
Keep the raw page text on each record so a suggestion can cite its source.

```python
@dataclass
class Asset:     name: str; value: int; currency: str
@dataclass
class Company:   company_id: str; name: str; hq_country: str
                 industry: str; assets: list[Asset]
                 related_entities: list[str]; source_page: int; raw_text: str
```

Validate hard, and fail the build if any of these break:

- exactly 100 profiles parsed
- every asset has an integer value and a 3-letter currency
- every `company_name` in the CSV resolves to a profile (all 100 do)
- each company's asset currencies are all its HQ country's currency

**Country → currency table.** Hand-write it in `currencies.py` as a plain dict,
then assert it against the currencies observed in the PDF. Both directions
agreeing is your evidence the table is right.

```python
COUNTRY_CURRENCY = {
    "Germany": "EUR", "Ireland": "EUR", "Spain": "EUR", "France": "EUR",
    "Italy": "EUR", "Netherlands": "EUR", "Portugal": "EUR", "Belgium": "EUR",
    "Austria": "EUR", "Finland": "EUR", "Luxembourg": "EUR",
    "United Kingdom": "GBP", "United States": "USD", "Switzerland": "CHF",
    "Sweden": "SEK", "Canada": "CAD", "Poland": "PLN", "Japan": "JPY",
}
```

**Loans → DuckDB.** One table, indexed on `company_name`. Source data is
immutable from here on; nothing downstream writes to it.

### Definition of Done
- [ ] `make up` brings OPA to a healthy `/health`
- [ ] `make ingest` regenerates `companies.json` and passes all four validations
- [ ] `SELECT count(*)` returns 100,000; 100 distinct companies
- [ ] The CSV `hq_country` column is asserted equal to the PDF and the assertion
      passes (it does — but the check is the point)

**Explain-it test:** point at any company profile in the PDF and have someone
show you the corresponding JSON record and the code path that produced it.

---

## Stage 2 — FX and enrichment

**Goal:** produce the exact input document OPA needs, with the external
dependency handled properly. This stage is where the brief is quietly testing
your engineering, not your arithmetic.

### Build

One call per run retrieves the Frankfurter EUR-base snapshot. EUR is implicit in
the response; the seven non-EUR currencies used by the loan data are validated
before the snapshot is accepted.

```python
def fetch_rates() -> tuple[dict, datetime, bool]:
    """Returns (rates_eur_base, fetched_at, degraded)."""
    try:
        r = httpx.get("https://api.frankfurter.dev/v1/latest",
                      params={"base": "EUR"}, timeout=10)
        r.raise_for_status()
        payload = r.json()
        save_cache(payload)
        return payload["rates"], now_utc(), False
    except Exception:
        cached = load_cache()                      # last good snapshot
        if age(cached) > MAX_STALENESS:
            raise FxUnavailable(...)               # fail loud, don't guess
        return cached["rates"], cached["fetched_at"], True
```

**The direction bug to avoid.** Frankfurter with `base=EUR` returns EUR→X, so
converting a USD loan into EUR is a *division*:

```python
loan_value_eur = loan_value if ccy == "EUR" else loan_value / rates[ccy]
```

Getting this inverted still produces plausible numbers and quietly moves
thousands of rows across the threshold. Unit-test it against a known rate.

Enrichment then adds four fields per row: `loan_value_eur`, `expected_currency`
(from the PDF profile via the table), `fx_rate_used`, `fx_fetched_at`. The last
two are stored on the verdict — without them you cannot reproduce a borderline
result tomorrow, and "the rate moved" is not an acceptable answer to a judge.

The implementation uses a maximum cache age of 24 hours. A successful live
request writes `data/fx_cache.json`; a failed request may use that cache and
marks the run `degraded=true`. Missing, malformed, or stale cache data fails
the run rather than guessing. The raw `loans` table is never modified. Outputs
are written to both the DuckDB `enriched_loans` table and
`data/enriched_loans.json`, whose metadata records the FX timestamp, degraded
status, and row count. Stage 2 makes no OPA or policy changes.

### Definition of Done
- [x] Exactly one FX HTTP call per full run (asserted in `tests/test_fx.py`)
- [x] Network failure falls back to a fresh cache and flags `degraded=True`
- [x] Staleness beyond 24 hours raises rather than silently proceeding
- [x] EUR-base division is tested against a fixed rate fixture
- [x] DuckDB and JSON enrichment outputs are tested while raw loans remain unchanged

**Explain-it test:** "what happens to this run if Frankfurter is down, and what
does the reviewer see?"

---

## Stage 3 — Rego policies and full-scale evaluation

**Goal:** all three verdicts for all 100,000 rows, produced by OPA, persisted.

### Build

One package, one entrypoint, batch-shaped input so you make ~100–200 HTTP calls
instead of 100,000:

```rego
package compliance
import rego.v1

min_loan_eur   := 25000
coverage_ratio := 0.5

decisions := [d |
    some loan in input.loans
    d := {
        "loan_id":    loan.loan_id,
        "rule1_pass": loan.loan_value_eur > min_loan_eur,
        "rule2_pass": loan.loan_currency == loan.expected_currency,
        "rule3_pass": loan.asset_value >= coverage_ratio * loan.loan_value,
    }
]
```

A comprehension over the array preserves order; a set would not. Post batches of
500–1,000 to `POST /v1/data/compliance/decisions` and write results to a
`verdicts` table alongside the FX metadata and a `policy_version`.

**Boundary tests — write these first.** The brief says *more than* EUR 25,000, so
25,000.00 exactly fails. Rule 3 says *at least* 50%, so exact 50% passes. Those
two asymmetries are the most likely thing a judge probes.

```rego
package compliance_test
import rego.v1
import data.compliance

test_r1_exactly_at_threshold_fails if {
    d := compliance.decisions with input as {"loans": [{
        "loan_id": "T1", "loan_value_eur": 25000, "loan_currency": "EUR",
        "expected_currency": "EUR", "asset_value": 999999, "loan_value": 1,
    }]}
    d[0].rule1_pass == false
}
```

### Definition of Done
- [x] `opa test policies/ -v` passes both boundary cases
- [x] Full 100k evaluation is implemented in 1,000-row batches
- [x] Rule 3 and Rule 1 reconciliation checks are covered by the evaluation query below
- [x] Every verdict row carries the rate, timestamp, and `stage3-v1` policy version

Stage 3 uses no LLM, embedding model, or RAG system. Rego evaluates structured
loan data deterministically. RAG begins in Stage 4 for finding and explaining a
replacement asset; the asset selection remains deterministic, so an LLM is
optional for explanation only.

Validation commands:

```powershell
.\\tools\\opa.exe test policies -v
.\\.venv\\Scripts\\python.exe -m pytest tests\\test_policy_evaluate.py -q
.\\.venv\\Scripts\\python.exe scripts\\run_evaluation.py
```

**Explain-it test:** hand someone a single failing `loan_id` and have them trace
it from CSV row → enrichment → OPA input JSON → policy line → stored verdict.

---

## Stage 4 — Suggestion agents

**Goal:** every failure gets a useful, *verified* proposed fix. Failures only —
roughly ten-odd thousand rows, not 100,000.

### Build

Route by rule. Two of the three need no model at all, and saying so out loud is a
better answer than pretending everything is agentic:

```python
def suggest(loan, verdict) -> Suggestion:
    if not verdict.rule1_pass:            # nothing to correct
        return remove_from_report(loan)   # template
    if not verdict.rule2_pass:            # deterministic lookup
        return change_currency(loan, expected_currency(loan))
    if not verdict.rule3_pass:            # retrieval + explanation
        return substitute_asset(loan)
```

**Rule 3, the RAG path.** The implementation is in `src/rag.py`. It retrieves
asset context from the matching company profile and filters
    assets clearing `0.5 × loan_value`, picks the **smallest qualifying** asset (least
over-collateralisation), and if none qualifies say so plainly rather than
proposing something that doesn't work. With 1–4 assets per company this is a
filter, not a search — the LLM's job is the explanation and the citation, not the
selection.

**Two mechanisms that make this stage credible:**

1. **Re-validate through OPA.** Apply the proposed fix to a copy of the row, send
   it back through the same policy, and only surface the suggestion if it now
   passes. Store the re-validation result next to the suggestion.
2. **Cache on `(company_id, rule, loan_value_bucket)`.** Suggestions do not
   depend on `loan_id`. 100 companies × 3 rules × a modest number of buckets
   collapses thousands of calls into hundreds.

**Evaluate retrieval, don't just assert it.** Hand-label ~50 failing rows with
the correct substitute asset (or "none exists"), and report accuracy against
that set. The brief says retrieval quality *and how you evaluate it* are both
assessed — a number here is worth more than any amount of description.

### Definition of Done
- [x] Every failing row has a suggestion. Rule-3 suggestions name a real asset
    from that company's profile or explicitly say none qualifies.
- [x] 100% of actionable suggestions pass OPA re-validation. Rows with no
    qualifying asset are explicitly reported as `no_qualifying_asset`.
- [x] Retrieval is deterministic and tested with qualifying, exact-boundary,
    and no-asset cases.
- [x] Cache hit rate and OPA revalidation count are reported by the runner.
- [x] A reproducible 50-row Rule 3 golden set is evaluated with
    `make evaluate-golden`.

The Stage 4 runner is:

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_suggestions.py
```

It reads only failed rows from `verdicts`, joins their enriched loan data,
loads `companies.json` once, and writes a `suggestions` table. The full run
produced 21,456 suggestions: 11,319 Rule 1, 5,332 Rule 2, and 4,805 Rule 3.
It reported a 97.3% cache hit rate and 385 OPA revalidations. There were zero
unverified actionable suggestions; 2,881 rows explicitly had no qualifying
asset.

The checked-in `data/golden_set_rule3.json` contains 50 deterministic regression
cases selected from the real Rule 3 failures. Expected values are the smallest
profile asset meeting the 50% threshold, or null when no asset qualifies. Run
`make evaluate-golden` to compare persisted suggestions with those labels.

Stage 4 uses exact company-key retrieval and deterministic asset filtering.
Embeddings are not needed for the 100-company, 1-4-assets-per-company data.
The current implementation makes zero LLM calls; its templates are easier to
audit. An LLM can be added later only for optional explanation wording, never
for asset selection or compliance decisions.

**Explain-it test:** show a rule-3 suggestion and have someone name the asset's
source page in the PDF and the reason that asset was chosen over the others.

---

## Stage 5 — Review application

**Goal:** a human can work through the failures at full scale without the tool
falling over.

### Build

API surface, deliberately small:

```
GET  /failures?rule=3&company=&cursor=&limit=100   -> page of failing rows
GET  /loans/{id}/suggestion                        -> generated or cached
POST /loans/{id}/action  {action, payload}         -> fix | ignore | accept
GET  /report                                       -> aggregates
```

Three things carry the scale requirement:

- **Query only failures**, server-side paged with a cursor on an indexed column.
  Never `SELECT *` the loans table.
- **Virtualise the rows** so the DOM holds ~30 nodes regardless of result size.
- **Lazy suggestions** for visible rows, with a background worker warming the
  cache ahead of the reviewer.

**Append-only action log.** Never update the loans table:

```sql
CREATE TABLE review_actions (
  id INTEGER PRIMARY KEY, loan_id TEXT NOT NULL,
  action TEXT CHECK(action IN ('manual_fix','ignore','accept_ai')),
  payload JSON, actor TEXT, created_at TIMESTAMP
);
```

Current state is derived from the latest action per loan. That gives you an audit
trail and undo for free, and it is the answer to "what if a reviewer makes a
mistake."

A manual fix re-runs OPA on the edited row, exactly like an accepted AI fix. Same
path, no special case.

### Definition of Done
- [ ] Table stays responsive with the full failure set loaded as a filter target
- [ ] All three actions work and are visible in the log
- [ ] A manual fix that still fails a rule is reported as still failing
- [ ] No endpoint returns an unbounded result set

**Explain-it test:** "what query runs when I scroll to row 4,000, and how many
rows does it return?"

---

## Stage 6 — Report, hardening, and only then the stretch

**Goal:** the artefact you put on screen in front of the judges, and a system
that survives being poked.

### Build

The report is SQL over `verdicts` and `review_actions`:

```sql
-- per-rule breakdown; a row can fail more than one rule
SELECT
  sum(NOT rule1_pass) AS rule1_failures,
  sum(NOT rule2_pass) AS rule2_failures,
  sum(NOT rule3_pass) AS rule3_failures,
  sum(NOT (rule1_pass AND rule2_pass AND rule3_pass)) AS failed_any,
  count(*) AS total_checked
FROM verdicts;
```

Plus: fixed manually vs accepted-from-AI vs ignored vs unresolved, total loan
value per company, and the run header — timestamp, FX rate, whether the run was
degraded, policy version.

State the per-rule counts *and* `failed_any` separately. Overlap between rules is
real here, and a single combined number is the thing the brief explicitly says
not to report.

The API exposes this report at `GET /report` in a small, readable JSON shape:

```json
{
    "total_checked": 100000,
    "rule1_failures": 12000,
    "rule2_failures": 8000,
    "rule3_failures": 5000,
    "failed_any": 18000,
    "review_status": {
        "manual_fix": 1000,
        "accept_ai": 500,
        "ignore": 200,
        "unresolved": 16300,
        "still_failing": 0
    },
    "per_company": [{"company_name": "Example Co", "loan_value_eur": 12345.0}],
    "run": {
        "timestamp": "2026-08-02T00:00:00Z",
        "fx_rates": {"EUR": 1.0},
        "fx_degraded": false,
        "policy_version": "stage3-v1"
    }
}
```

`still_failing` is reported separately when a manual or AI action was recorded
but its mandatory OPA re-validation still failed. The report reads the
append-only action log and never changes loan or verdict rows.

**Hardening pass:** re-run end to end from a clean checkout with `make`; confirm
the demo path works with the network flaky; check the report reconciles against
raw SQL on the CSV.

**Stretch, only if all of the above is solid.** A regression on asset value with
features from HQ country/region, industry, loan value and asset type parsed from
the description. Use `GroupKFold` grouped by company so the same company cannot
appear in train and test — that grouping *is* the methodology answer, because
with 100 companies and 100k rows a random split leaks badly and produces a
flattering, meaningless RMSE. Convert to EUR before computing RMSE and state the
unit.

### Definition of Done
- [x] Per-rule counts, `failed_any`, review statuses, company totals, and run
    metadata are exposed by `GET /report`
- [x] Every judge-facing report field traces to a SQL query or persisted run
    metadata, and Stage 6 report behavior is covered by focused tests
- [ ] Report numbers reconcile against independent SQL on the raw CSV
- [ ] Clean-checkout run works in one command
- [ ] If attempted: RMSE reported with the split described, not just the number

**Explain-it test:** a dry run of the presentation where each person answers a
question about someone else's stage.

---

## Sequencing across the four days

| Day | Stages |
|---|---|
| Before day 1 | Stage 1 skeleton: repo, Compose, OPA healthy, FX reachable |
| Day 1 PM | Stage 1 complete; Stage 3 spiked with rule 1 only on a 1,000-row sample |
| Day 2 | Stage 2 complete; Stage 3 complete on full 100k; Stage 4 for rules 1 and 2 |
| Day 3 | Stage 4 rule 3 with re-validation; Stage 5 at full scale; Stage 6 report. Stretch only after all of this holds |
| Day 4 AM | Demo and defence |

If day 3 is going badly, cut the stretch goal, then cut UI polish, then cut rule
3's LLM explanation down to a template — in that order. Do not cut the OPA
re-validation loop or the tests; they are the parts that prove the system is
engineered rather than generated.
