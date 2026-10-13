# finagent — Hallucination-Resistant Financial Research Agent

A financial research agent that answers natural-language questions about US public company fundamentals using SEC EDGAR XBRL data. The system is architected so the LLM never emits raw numbers: every numeric cell in output tables is computed deterministically from cached SEC facts, each with an immutable provenance link back to the original filing. Claims produced by the summarizer are verified against the evidence bundle before they reach the user; unsupported claims are either rewritten or downgraded. The result is near-zero hallucination on numeric content, at the cost of a more constrained output format.

Current scope covers four US tech tickers (AAPL, MSFT, NVDA, GOOG) across eight calendar quarters (CY2023Q1–CY2024Q4).

## Setup

**Prerequisites:** Python 3.11+, `OPENAI_API_KEY`, SEC contact info (name + email for the User-Agent header required by SEC EDGAR).

```bash
# Clone and install
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# Required environment variables
export OPENAI_API_KEY=sk-...
export SEC_NAME="Your Name"
export SEC_EMAIL="your.email@example.com"

# Optional: model override (default: gpt-4o)
export FINAGENT_MODEL=gpt-4o

# Optional: custom profile path (default: ~/.finagent/profile.json)
```

The SEC contact info is used solely to build the `User-Agent` header per SEC EDGAR access guidelines — it is not sent anywhere else. The cache is stored at `./cache/http.sqlite` and populated lazily as queries are made.

## Usage

Run a query from the command line:

```bash
# Via console_scripts entry point (pip install creates the command)
finagent --question "What was AAPL revenue for CY2024Q1?"

# Or via module invocation
python -m finagent.app --question "Compare revenue for AAPL, MSFT, GOOG across the last 4 quarters."

# Export result to XLSX
finagent --question "NVDA net income trend, last 4 quarters" --xlsx output/nvda-trend.xlsx

# Use a custom profile
finagent --question "..." --profile path/to/profile.json --verbose
```

XLSX export produces a three-sheet workbook: Table (the data table), Facts (every fact used, with provenance URLs), and Claims (summary claims with verdict status).

## Design Decisions

### Plan-Execute Architecture

The pipeline runs in five phases: (1) the planner LLM resolves tickers, browses available concepts, and emits a structured `QueryPlan`; (2) facts are fetched from the SEC cache and a table is built deterministically; (3) an evidence bundle is assembled from the raw facts; (4) the summarizer LLM writes claims that cite evidence IDs; (5) a three-gate verifier checks every claim against the evidence bundle, and failed claims trigger a rewrite loop or are dropped.

### Three Invariants

1. **The LLM never emits numbers.** All numeric values in output tables come from deterministic computation over cached SEC facts (raw lookup, YTD differencing, or ratio derivation). The LLM only selects which metrics and periods to show — it does not produce numeric output.
2. **Provenance is unstrippable.** Every cell in the output table carries a `fact_id` that resolves in the evidence index to a fact with full provenance (accession number, filing date, form type, source URL, XBRL viewer URL). The verifier confirms that the cell's displayed value equals the stored fact value.
3. **The LLM does semantic work only.** Interpretation claims (qualitative analysis) are permitted and auto-pass the number gate, but every datapoint claim must cite evidence whose display string contains the exact number used.

### Fact and Provenance Model

- **Fact** is an immutable dataclass with `fact_id` (content-hashed), raw `value` (Decimal), `unit`, `concept`, period dates, `frame`, and a nested **Provenance** record.
- Facts are normalized from the SEC `companyfacts` JSON: revisions are deduplicated (latest filing wins), cumulative periods are differenced to derive single-quarter values, and calendar frames are assigned from period-end dates.
- Derived facts (gross margin via ratio, YTD-differenced quarters) carry their own fact IDs and track the input facts they were computed from.

### Revision Deduplication, YTD Differencing, and Calendar Frames

- **Revision dedup:** facts with the same (concept, period_start, period_end) collapse to the latest filing, so amended 10-Qs do not produce duplicate rows.
- **YTD differencing:** when a company reports only cumulative (H1, 9M, FY) values for a concept, single-quarter values are derived by subtracting the longest available prefix cumulative. Derived facts are marked `derived:YTD_DIFF` in provenance so they can be distinguished from natively reported single-quarter numbers.
- **Calendar frames:** each fact is assigned a `CY####Q#` frame based on its period-end date, so cross-company tables align on calendar quarters even when companies have different fiscal year-ends.

### Three-Gate Claim Verification

Every datapoint claim passes through sequential gates:

1. **Evidence gate:** every cited evidence ID must exist in the index.
2. **Number gate:** every numeric token in the claim text must match (exact Decimal equality, same percent flag) at least one bound evidence display string.
3. **Judge gate:** an LLM judge confirms the claim is supported (not contradicted, not merely not-contradicted) by the cited evidence.

Claims that fail are fed back to the summarizer for rewrite (up to `max_rewrites` attempts). If all attempts fail, datapoint claims are dropped (counted in `downgraded`), while interpretation claims are always retained.

### Profile Adaptation

A user profile (stored as JSON at `~/.finagent/profile.json`) configures the default watchlist, metric aliases, default number of quarters, and display preferences. The planner is primed with this profile so it can use user-provided aliases for metric names.

## Evaluation

### Golden Set

The evaluation uses 15 hand-curated cases across five categories (3 single-company, 3 trend, 4 multi-company, 3 narrative, 2 adversarial). Each case records the question, expected plan highlights, expected cell values, and expected behavior (answer / produce_table / ask / degrade).

Golden values are fixture-contract values defined in `finagent/eval/fixtures.py` for offline scoring. A test asserts bidirectional consistency between `golden.yaml` and the fixtures. Before a published eval run, values must be re-verified against live SEC EDGAR data.

### Metrics

| Metric | Definition |
|---|---|
| Numeric accuracy | Fraction of golden table cells matched within 0.01 tolerance |
| Provenance validity | Fraction of numeric cells with a valid fact_id whose linked fact value equals the shown value |
| Hallucination rate | Fraction of claims that fail verification |
| Task completion | Whether requested deliverables (table / summary) were produced |
| Boundary correctness | Whether ask/degrade cases are handled appropriately (no fabrication) |

### Baselines

Two baselines are evaluated alongside the harness, both using the same underlying model:

1. **Bare prompt** — the model with a single free-form prompt, no tools, no structured output. Emulates the ChatGPT web product.
2. **Linked prompt** — bare prompt with SEC EDGAR context, to control for the advantage of internet access.

Baseline numbers are extracted heuristically from free-form text. Provenance validity is always ~0 for baselines (they produce no fact links). Hallucination rate is approximated from numeric mismatch.

### Running the Evaluation

**Offline (unit tests — no network, no API key):**

```bash
python -m pytest -q
```

This proves the scoring logic is correct. 125+ tests cover all metrics, boundary cases, the golden-yaml/fixture consistency check, and the end-to-end runner with scripted doubles.

**Live (requires OPENAI_API_KEY + SEC contact):**

```bash
python -m finagent.eval.run_eval --out eval-report.md
```

This runs all 15 cases through the full harness and both baselines, producing a markdown report with per-case results and aggregate means. The SEC cache is populated lazily; the first run will be slower as it fetches company facts.

### Reading the Report

The markdown report contains three sections:

- **Per-Case Results:** every case scored across all three modes (harness / bare / linked).
- **Aggregate Comparison:** overall mean scores for each mode — the headline numbers.
- **Per-Category Breakdown:** means grouped by category (single, trend, multi_company, narrative, adversarial).

Expected outcome: the harness leads decisively on numeric accuracy (especially for derived values and YTD differences), provenance validity (~100% vs ~0%), and hallucination rate. Baselines may win on cost and latency, which is reported honestly.

## Project Layout

```
finagent/
  app.py                 # End-to-end orchestration + CLI entry point
  config.py              # Configuration from environment
  models.py              # Core immutable dataclasses (Fact, Claim, QueryPlan, etc.)
  metrics.py             # Scaling, ratio, YoY computation
  cache.py               # HTTP response cache (SQLite)
  datasource/
    sec_client.py        # SEC EDGAR HTTP client
    tickers.py           # Ticker-to-CIK resolver
    taxonomy.py          # Concept alias / taxonomy mapping
    facts.py             # Fact normalization, dedup, YTD differencing, framing
  agent/
    llm.py               # OpenAI wrapper with structured JSON output
    tools.py             # Data retrieval tools used by the planner loop
    planner.py           # Planner schema definitions
    loop.py              # Agent loop: plan with tool calls and validation
  output/
    table.py             # Deterministic table builder
    cli.py               # Console renderer
    xlsx.py              # Three-sheet XLSX exporter
  narrative/
    summarizer.py        # Evidence bundle builder, claims parser
    verifier.py          # Three-gate claim verifier
  profile/
    store.py             # User profile persistence
  eval/
    golden.yaml          # 15-case golden evaluation set
    fixtures.py          # Canonical offline fixture values
    run_eval.py          # Scoring functions + evaluation runner + baselines
tests/
  eval/
    test_metrics.py      # Scoring function tests, golden consistency, runner tests
```

## Limitations

- **Four-ticker universe:** the demo is scoped to AAPL, MSFT, NVDA, GOOG. The architecture generalizes, but evaluation and caching have only been exercised on these four.
- **Calendar framing for off-fiscal-year companies:** companies with fiscal years that do not align with calendar years (e.g., AAPL's FY ends in September) are mapped to calendar quarters by period-end date. This means "AAPL FY2024 Q1" and "AAPL CY2024 Q1" refer to different periods; the agent uses calendar frames consistently.
- **Live SEC smoke test is manual:** the test suite is fully offline. There is no automated CI test against live SEC data; a manual smoke test is recommended before production use.
- **No streaming output:** the CLI prints the full result only after all phases complete.
