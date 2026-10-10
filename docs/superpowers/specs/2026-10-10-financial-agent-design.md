# Financial Research Agent — Design Spec

**Date:** 2026-10-10
**Scope:** An agentic harness over GPT for equity research analysts, focused on US-listed technology companies. The harness retrieves and summarizes public financial statements and produces cross-quarter comparison tables with cell-level provenance so every generated number can be checked against the SEC source.

---

## 1. Problem and Thesis

Analysts fear making decisions on hallucinated data. Vanilla ChatGPT produces financial figures from parametric memory: numbers can be outdated, drawn from the wrong company/period, or silently computed, with no way to verify them.

**Thesis:** the harness wins by making grounding an *architectural invariant*, not a prompt request. The LLM never emits a number. Every number in every output is a reference to an immutable `Fact` sourced from the SEC XBRL API, carried through the pipeline with full provenance. Narrative claims must cite evidence, and an independent verifier rejects or downgrades anything unsupported.

**Coverage decisions (confirmed):**

- Market / sector: US equities, technology sector (e.g. AAPL, MSFT, NVDA, GOOG).
- Interface: CLI / REPL with Markdown-style tables and xlsx/CSV export.
- LLM: OpenAI official API (gpt-4o-class model with structured outputs / function calling); hand-rolled orchestration, no LangChain.
- Provenance: cell-level, with SEC filing deep links.
- Narrative anti-hallucination: claims bound to evidence + an independent verification stage.
- User adaptation: local analyst profile (watchlist, metric aliases, preferences).
- Evaluation: fixed golden set + ChatGPT baselines, quantitative metrics.

---

## 2. Architecture Overview

Approach: **Plan–Execute over a deterministic data layer.** The LLM does only semantic work (intent parsing, alias mapping, narration over supplied facts); code owns every number.

```
finagent/
  config.py              # config loading (API keys, SEC User-Agent, paths)
  models.py              # Fact, Provenance, Claim, QueryPlan, table models
  datasource/
    sec_client.py        # SEC EDGAR / data.sec.gov client (rate limit, cache)
    tickers.py           # ticker -> CIK resolution (company_tickers.json)
    taxonomy.py          # metric alias -> us-gaap concept mapping
    facts.py             # companyfacts fetch, normalization, period alignment
  agent/
    llm.py               # OpenAI client wrapper (structured JSON output)
    planner.py           # user question -> QueryPlan
    tools.py             # read-only tools the agent may call
    loop.py              # plan-execute ReAct loop
  narrative/
    summarizer.py        # generates claims over an evidence bundle
    verifier.py          # rule checks + LLM-as-judge fact verification
  output/
    table.py             # deterministic quarter-aligned comparison table
    xlsx.py              # xlsx export: data + provenance + claims sheets
    cli.py               # REPL rendering (rich tables, citation markers)
  profile/
    store.py             # local analyst profile persistence (JSON)
  eval/
    golden.yaml          # fixed questions with hand-verified answers
    run_eval.py          # run harness + ChatGPT baselines, score metrics
  cache/                 # on-disk HTTP/fact cache
```

### Request lifecycle

```
User prompt (may reference "my companies", "last few quarters")
   |
   v
[Planner / ReAct loop] --calls--> read-only tools
   |  emits QueryPlan {companies, line_items, period range, outputs}
   v
[Data layer fetch] --> SEC companyfacts API --> normalized immutable Facts
   |  (deterministic; cache; numbers are "fixed" at this point)
   v
[Table builder] aligns by fiscal/calendar period; cell = value + fact_id
   |
   +--> [Summarizer] receives evidence bundle only; emits claims[]
   |         v
   |    [Verifier] rules + independent LLM judge
   |         v  reject --> rewrite (bounded) or downgrade (explicit)
   v
[Renderer] CLI (table + footnote citations) / xlsx (3 sheets, hyperlinks)
```

### Three architectural invariants

1. **Single source of numbers.** Every output number is a reference to a `Fact`. Bare numbers in LLM output are rejected by the verifier.
2. **Provenance cannot be stripped.** Facts carry `accession + concept + period + url` from API to cell; the renderer cannot emit a cell without provenance.
3. **LLM does semantic work only.** Intent, aliases, narration — no arithmetic. Computed metrics (YoY, margins) are produced by deterministic code as `DerivedFact`s whose provenance records their input fact ids.

---

## 3. Data Layer: Fact and Provenance Model

### Core models (`models.py`)

```python
@dataclass(frozen=True)
class Provenance:
    accession: str            # e.g. "0000320193-24-000123"
    form: str                 # "10-K" / "10-Q"
    filed_date: str           # YYYY-MM-DD
    fiscal_period: str        # "Q1".."Q4" / "FY"
    fiscal_year: int
    concept: str              # full us-gaap concept name
    source_url: str           # direct link to the filing document
    xbrl_fact_url: str        # deep link to the fact in the SEC viewer
    raw_value: str            # original string from the API (audit)

@dataclass(frozen=True)
class Fact:
    fact_id: str              # content hash, used for dedup/reference
    cik: int
    ticker: str
    company_name: str
    value: Decimal            # Decimal, never float
    unit: str                 # "USD" / "USD/shares" / "shares"
    concept: str
    period_start: date
    period_end: date
    frame: str | None         # SEC calendar frame, e.g. "CY2024Q1"
    provenance: Provenance

@dataclass(frozen=True)
class DerivedFact:
    fact_id: str
    value: Decimal
    formula: str              # operator name, e.g. "ratio" / "yoy" / "ytd_diff"
    input_fact_ids: tuple[str, ...]
```

Design points:

1. **Immutability and Decimal.** Frozen dataclasses + content-hash ids mean LLM code can only reference facts, never alter them. Decimal eliminates float error in monetary figures.
2. **10-K vs 10-Q dedup / revisions.** The same (concept, period) may be reported in multiple filings. Deterministic rule: prefer the value in the *latest filed* 10-K/10-Q for that period (revisions are more trustworthy); provenance retains all sources so a cell can be expanded to show original vs revised. This is a concrete edge ChatGPT gets wrong (stale preliminary values).
3. **Quarter alignment.**
   - Prefer the SEC `frame` (`CY2024Q1`) so companies with different fiscal years (AAPL ends Sep, NVDA ends Jan) align to the same calendar quarter.
   - When no frame exists, match by `(period_start, period_end)` window: quarter ~90 days, year ~365 days, ±7 day tolerance.
   - **YTD cumulative to single quarter:** 10-Q values are cumulative (6/9 months). Single-quarter Q2 = H1 − Q1, computed deterministically as a `DerivedFact` with both inputs recorded.
   - Fiscal-year misalignment is not erased; it is footnoted in the table (e.g. "NVDA FY2025Q4 ≈ calendar 2024Q4").
4. **Concept mapping (`taxonomy.py`).** Each metric alias maps to an ordered *fallback list* of us-gaap tags (newer companies use `RevenueFromContractWithCustomerExcludingAssessedTax`; older filings use `Revenues`). The mapping is static code + yaml data, never LLM-generated. For metrics outside the built-in set, the planner uses a tool to discover concepts a company actually filed and may persist the confirmed mapping to the profile.
5. **SEC client compliance (`sec_client.py`).**
   - Mandatory identifying `User-Agent: name email` (required by SEC).
   - Rate limit ≤ 10 req/s (conservative ~5 req/s).
   - Endpoints: `submissions/CIK##########.json`, `xbrl/companyconcept/...`, `xbrl/companyfacts/...`.
   - All responses cached on disk (sqlite, keyed by URL, with etag): offline re-runs, reproducible evaluation, no redundant calls.
6. **Missing means missing.** If a company did not file a concept for a quarter, the cell renders `N/A` with the reason "not reported by this company". Never blanks that invite LLM fill-in; never cross-company value borrowing.

---

## 4. Agent Loop, Tools, and QueryPlan

### QueryPlan (strict JSON schema)

```json
{
  "companies": [{"ticker": "AAPL", "cik": 320193}],
  "line_items": [
    {"alias": "revenue",
     "concepts": ["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                  "us-gaap:Revenues"],
     "unit": "USD", "scaling": "millions"},
    {"alias": "gross_margin", "kind": "derived", "formula": "gross_profit/revenue"}
  ],
  "periods": {"type": "last_n_quarters", "n": 4},
  "outputs": ["table", "xlsx", "summary"]
}
```

### ReAct loop (`agent/loop.py`)

Finite state; tools are read-only; no tool lets the LLM write a number.

```
state: messages[]
loop (max K turns):
    resp = LLM(system prompt + question + profile summary + messages)
      | structured output:
      +- tool_call -> validate args against JSON schema
      |                result = TOOLS[name](args)   # deterministic, read-only, cached
      |                append result
      +- finalize(QueryPlan) -> schema + deterministic validation -> fetch
```

### Tools (`agent/tools.py`) — four, small attack surface

| Tool | Purpose | Returns |
|---|---|---|
| `resolve_ticker(ticker)` | ticker -> CIK, fuzzy correction | CIK, official name; candidates if ambiguous |
| `list_concepts(cik, query)` | us-gaap tags the company actually filed | tags + most recent filing periods |
| `list_available_periods(cik)` | quarters/years with data | frame list |
| `preview_metric(cik, concept, period)` | one-point sample probe to confirm a tag is correct | value + unit + provenance summary |

`preview_metric` prevents the most common alias error — selecting a near-synonym wrong tag (revenue vs deferred revenue) — by letting the planner self-check against a real sample before fetching.

### Deterministic plan validation (fail -> replan)

1. Every company CIK must have been verified via `resolve_ticker`.
2. Every line-item concept must be in that company's filed concept set.
3. Derived-formula inputs must exist in the plan or be expressible by built-in operators.
4. Requested periods must lie within the intersection of available periods; fewer than N quarters degrades to the available count with a notice — fabricating quarters is impossible.

### Hard constraints (system prompt; verifier backstops)

- You do not supply numbers; numbers from memory are untrusted. You only plan retrieval.
- Resolve company-name ambiguity with the user (e.g. "apple" -> confirm Apple Inc.).
- Metric ambiguity ("income": revenue vs net income) is resolved first by the profile, then by asking.

### Profile participation

- The planner context injects `watchlist`, `metric_aliases`, `default_quarters`, and unit/scaling preferences.
- Profile mutations ("add NVDA to my watchlist", "by 'income' I mean revenue") produce a `profile_update` intent; the CLI shows the diff and asks for confirmation; deterministic code writes the file. The LLM never writes files directly.

### Explicit user-clarification cases

1. Company/metric ambiguity not resolvable from profile -> CLI presents choices.
2. Request out of data range (e.g. 2015 quarter for a 2018 IPO) -> state available range and confirm.

---

## 5. Narration and Verification

### Summarizer contract (`narrative/summarizer.py`)

Input is an **evidence bundle** (facts and derived facts, each with id, label, value, unit, period). Output is a structured claim list, not free prose:

```json
{"claims": [
  {"id": "c1",
   "text": "AAPL 2024Q1 revenue grew 5.4% year over year.",
   "evidence_ids": ["d_yoy_aapl_rev", "f_aapl_rev_q1", "f_aapl_rev_prev"],
   "claim_type": "datapoint"},
  {"id": "c2",
   "text": "Revenue performance was solid this quarter.",
   "evidence_ids": [],
   "claim_type": "interpretation"}
]}
```

- `datapoint` claims (anything with numbers, comparisons, trends, rankings) must bind ≥1 evidence id.
- `interpretation` claims (no numbers) may have empty evidence but are rendered with the forced prefix `【模型解读，非数据】` so interpretation can never masquerade as fact.
- No third claim type; no companies/metrics/periods outside the evidence bundle.

### Verifier — three gates (`narrative/verifier.py`)

**Gate 1 — Reference integrity (rules).**
- Every evidence id exists; every datapoint has non-empty evidence.
- All numbers/percentages/amounts extracted from claim text are checked: each must be explainable by bound evidence values (after deterministic unit/scaling conversion) or by deterministic derivation (difference, ratio, multiple). Display precision is tolerated.
- Unattributable bare numbers are rejected outright.

**Gate 2 — Evidence support (independent LLM-as-judge).**
- A separate LLM call with fresh context sees only the claim and evidence values (not the user question, avoiding sycophantic drift) and returns `supported / contradicted / not_grounded`.
- The judge may output an arithmetic expression, which code re-evaluates so the judge itself cannot introduce arithmetic error.

**Gate 3 — Scope checks (rules).**
- Company/ticker/quarter tokens in a claim must be within plan scope.
- Unsupported superlatives ("industry leader", "beat all peers") are blocked by keyword + evidence requirements.

### Disposition

```
all pass                    -> emit
rejected claims             -> feed itemized reasons back; rewrite, max 2 attempts
still failing after 2       -> do not silently drop or emit as-is:
                               claim is hidden from the body; an explicit footnote
                               "N claim(s) failed verification; see --verbose"
                               with reasons provides an audit trail
```

Tables undergo the same mechanism: every non-N/A cell resolves to a fact; derived cells are recomputed; the provenance sheet has exactly the distinct referenced facts (no orphans, none missing).

---

## 6. Output, xlsx Export, and Analyst Profile

### CLI rendering (`output/cli.py`, rich)

- Numeric cells carry citation markers; `:source N` prints full provenance and SEC links.
- Derived rows show the operator and can expand to input facts.
- N/A cells carry reasons; interpretations are visually separated; the verification tally is always displayed.

### xlsx export (`output/xlsx.py`, openpyxl) — self-auditing workbook

- **Sheet `Comparison`:** pivot of company × metric by quarter; every numeric cell hyperlinks to the SEC fact URL; cell comments hold concept, accession, filed date, raw value, unit (and formula + input accessions for derived cells).
- **Sheet `Provenance`:** one row per fact — fact_id, company, ticker, concept, period_start/end, frame, raw_value, value, unit, form, accession, filed_date, source_url.
- **Sheet `Claims`:** claim_id, text, type, evidence_ids, verdict, judge_reason.
- Each comparison value is traceable into the Provenance sheet by fact_id.
- Exports are timestamped and accompanied by a JSON snapshot of the fact bundle under `output/snapshots/`, so a workbook is reproducible from cache long after the run.

### Analyst profile (`profile/store.py`)

Single JSON file, default `~/.finagent/profile.json`, switchable via `--profile name`:

```json
{
  "watchlist": [{"ticker": "NVDA", "cik": 1045810, "added": "2026-10-10"}],
  "metric_aliases": {"收入": "revenue"},
  "default_quarters": 4,
  "preferences": {"units": "USD", "scaling": "millions",
                  "show_derived_formula": true},
  "confirmed_resolutions": {"apple": "AAPL"}
}
```

Read/write separation: the LLM only proposes updates; the CLI displays a diff and requires confirmation; deterministic code writes. The planner receives a summary, not the whole file. Queries like "revenue of my companies over the last two quarters" resolve directly without re-asking.

---

## 7. Evaluation

### Golden set (`eval/golden.yaml`) — 15 fixed, hand-verified questions

| Category | # | Example | Tests |
|---|---|---|---|
| Single company, single metric | 3 | "AAPL revenue for 2024Q1" | basic retrieval |
| Single company, multi-quarter trend | 3 | "NVDA gross margin, last 4 quarters" | YTD differencing, fiscal misalignment |
| Multi-company cross-quarter table | 4 | "Compare AAPL/MSFT/GOOG revenue, last 4 quarters, export xlsx" | alignment, provenance completeness |
| Narrative summary | 3 | "Summarize AAPL's last two quarters" | claim binding, interpretation separation |
| Adversarial / boundary | 2 | ambiguous "apple income"; NVDA in 2010 (out of range) | clarification / degradation instead of guessing |

Each entry records the question, expected plan highlights, numeric answers (± display precision tolerance), and expected behavior (ask / degrade).

### Metrics

| Metric | Definition |
|---|---|
| Numeric accuracy | Fraction of output numbers matching golden (table cells and claim numbers scored separately) |
| Provenance validity | Fraction of citations whose link resolves and whose linked fact value equals the cell value (script-verified via cache) |
| Hallucination rate | Fraction of claims containing unsupported numbers or judged contradicted / not_grounded |
| Task completion | Whether all requested deliverables (table / xlsx / summary) were produced |
| Boundary correctness | Correct clarification/degradation on ambiguous/out-of-range cases |
| Cost / latency | Token usage and wall time (secondary) |

### Baselines (`run_eval.py`)

1. **Harness** — this system.
2. **ChatGPT baseline** — the same model with a single bare prompt (no tools, no files), asked for tables and summaries, emulating the web product.
3. **ChatGPT+ (fairness check)** — bare prompt with SEC links supplied, to show the advantage is not merely internet access.

The same provenance/hallucination checks are applied to baseline output (baseline numbers typically have no citations → provenance ≈ 0; stale or mismatched numbers surface in hallucination scoring). The runner emits a markdown comparison report. Expected result: the harness leads decisively on numeric accuracy (especially revisions and YTD differences), provenance validity (~100% vs ~0), and hallucination rate; baselines may win on cost/latency, which is reported honestly.

---

## 8. Error Handling Summary

- Bad tool arguments / malformed structured output: schema error fed back to the model; bounded retries.
- SEC API failures (429 / 5xx / network): retry with backoff; on persistent failure, report which company/period is unavailable rather than substituting data; cache allows partial offline answers.
- Unresolvable ambiguity: explicit user question, never a guess.
- Repeated verification failure: explicit downgrade with audit trail, never silent drop nor unchecked emit.
- Missing filings/concepts: `N/A` with reason.

## 9. Testing Strategy

- Unit tests for the deterministic core: SEC payload normalization, 10-K/10-Q dedup, YTD differencing, calendar-frame alignment, unit/scaling conversion, derived-formula arithmetic — using recorded SEC fixtures.
- Schema/contract tests for QueryPlan, evidence bundle, and claims.
- Verifier tests with crafted claims (correct, bare number, contradicted, out-of-scope, bad arithmetic).
- Tool tests against cached responses (no live calls in CI).
- End-to-end tests on a small set of golden prompts run fully from cache; outputs asserted numerically and structurally.
- LLM calls in tests are replayed or run as a separate, opt-in integration tier.

## 10. Key Features (performance drivers, for interview)

1. Deterministic data channel with immutable XBRL facts — LLM structurally cannot invent numbers.
2. Cell-level provenance with SEC deep links, including original-vs-revised sources.
3. Correct cross-company/cross-quarter alignment (calendar frames) and YTD-to-quarter differencing.
4. Claim/evidence binding with a three-gate independent verifier and explicit degradation.
5. Local analyst profile for adaptation without granting the LLM write access.
6. Cached, reproducible runs and a quantitative golden-set evaluation against ChatGPT baselines.
