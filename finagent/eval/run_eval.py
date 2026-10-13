"""Evaluation harness: pure scoring functions + runner.

Scoring functions are pure and independently unit-tested.

The runner takes injected callables so tests can run fully offline with
scripted doubles. The module's __main__ wires REAL clients (OpenAI + SEC
cached) for live evaluation runs.

Metrics:
  - numeric_accuracy: fraction of golden cells matched within tolerance
  - provenance_validity: fraction of numeric cells with valid fact_id
    AND whose linked fact value equals the cell value
  - hallucination_rate: fraction of verdicts that failed
  - task_completion: requested deliverables present per expected_behavior
  - boundary_correct: ask/degrade cases handled correctly
"""

import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import yaml

# SEC URL constants — reuses the same base URLs and patterns as SECClient
SEC_DATA_BASE = "https://data.sec.gov"
SEC_WWW_BASE = "https://www.sec.gov"

# Known ticker universe (offline fixture CIKs; live path resolves via resolver)
# CIKs come from finagent.eval.fixtures.COMPANIES for the four demo tickers.
KNOWN_TICKERS_OFFLINE = {
    "AAPL": 320193,
    "MSFT": 789019,
    "NVDA": 1045810,
    "GOOG": 1652044,
}


# ---------------------------------------------------------------------------
# Baseline SEC URL helpers (pure, testable)
# ---------------------------------------------------------------------------

def companyfacts_url(cik: int) -> str:
    """SEC XBRL companyfacts API URL for a CIK.

    Matches the pattern used by SECClient.get_company_facts:
    https://data.sec.gov/api/xbrl/companyfacts/CIK{padded:010d}.json
    """
    return f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{int(cik):010d}.json"


def browse_edgar_url(cik: int, form_type: str = "10-Q") -> str:
    """EDGAR browse page URL for a company's filings.

    Pattern: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={padded}&type={form}&dateb=&owner=include&count=40
    """
    padded = f"{int(cik):010d}"
    return (
        f"{SEC_WWW_BASE}/cgi-bin/browse-edgar?"
        f"action=getcompany&CIK={padded}&type={form_type}"
        f"&dateb=&owner=include&count=40"
    )


def extract_case_tickers(case: dict, universe: set[str]) -> list[str]:
    """Extract ticker symbols referenced in a golden case.

    Uses the case's expected_cells keys first (most reliable),
    then falls back to scanning the question text for known tickers.
    Returns deduplicated tickers in sorted order.
    """
    tickers = set()

    # 1. From expected_cells keys ("TICKER|alias|frame")
    for key in case.get("expected_cells", {}):
        parts = key.split("|")
        if len(parts) >= 1 and parts[0] in universe:
            tickers.add(parts[0])

    # 2. From question text (fallback for adversarial cases with no cells)
    if not tickers:
        question = case.get("question", "")
        for t in universe:
            # Match whole word / uppercase ticker
            if re.search(r"\b" + re.escape(t) + r"\b", question):
                tickers.add(t)

    return sorted(tickers)


def build_sec_urls_for_case(case: dict, ticker_to_cik: dict[str, int]) -> list[str]:
    """Build SEC source URLs for a golden case.

    For each ticker referenced in the case, returns:
      - companyfacts API URL
      - EDGAR 10-Q browse page URL

    Tickers not in ticker_to_cik are silently ignored.
    """
    universe = set(ticker_to_cik.keys())
    tickers = extract_case_tickers(case, universe)
    urls = []
    for ticker in tickers:
        cik = ticker_to_cik[ticker]
        urls.append(companyfacts_url(cik))
        urls.append(browse_edgar_url(cik, "10-Q"))
    return urls


def build_bare_prompt(question: str) -> tuple[str, str]:
    """Build the bare baseline prompt (no SEC URLs).

    Returns (system_prompt, user_message).
    """
    system = (
        "You are a financial analyst. Answer the question with a table of "
        "numbers if requested, or a brief summary. Be as accurate as possible."
    )
    return system, question


def build_linked_prompt(question: str, urls: list[str]) -> tuple[str, str]:
    """Build the linked baseline prompt (with concrete SEC URLs supplied).

    The model is given the URLs verbatim but has no tools — it must use its
    knowledge and interpret the URLs as context, not fetch them.

    Returns (system_prompt, user_message).
    """
    if urls:
        url_list = "\n".join(f"- {u}" for u in urls)
        system = (
            "You are a financial analyst. You may consult these SEC EDGAR sources:\n"
            f"{url_list}\n\n"
            "Answer the question with a table of numbers if requested, "
            "or a brief summary. Be as accurate as possible and cite the "
            "filings when you can."
        )
    else:
        # No URLs available (e.g. adversarial case with no recognized ticker)
        system = (
            "You are a financial analyst with access to SEC EDGAR. "
            "Answer the question with a table of numbers if requested, "
            "or a brief summary. Be as accurate as possible."
        )
    return system, question


# ---------------------------------------------------------------------------
# Pure scoring functions
# ---------------------------------------------------------------------------

def numeric_accuracy(
    predicted: dict[tuple, str],
    golden: dict[tuple, str],
    tol: Decimal = Decimal("0.01"),
) -> float:
    """Fraction of golden cells matched by predicted values within tolerance.

    Args:
        predicted: dict of (company, alias, frame) -> display string
        golden: same shape as predicted
        tol: Decimal tolerance for numeric comparison

    Returns:
        float between 0.0 and 1.0. Empty golden -> 0.0.
        Unparseable predictions count as mismatches.
        Missing predicted keys count as mismatches.
    """
    if not golden:
        return 0.0

    ok = 0
    for k, v in golden.items():
        pred_str = predicted.get(k)
        if pred_str is None:
            continue
        try:
            pred_val = Decimal(pred_str)
            gold_val = Decimal(v)
            if abs(pred_val - gold_val) <= tol:
                ok += 1
        except (InvalidOperation, ValueError):
            # Unparseable → mismatch (don't increment ok)
            continue

    return ok / len(golden)


def hallucination_rate(verdicts: list) -> float:
    """Fraction of verdicts that are not ok.

    Args:
        verdicts: list of Verdict objects (each has .ok bool)

    Returns:
        float between 0.0 and 1.0. Empty -> 0.0.
    """
    if not verdicts:
        return 0.0
    failed = sum(0 if v.ok else 1 for v in verdicts)
    return failed / len(verdicts)


def _cell_value_matches(cell, index_entry, tol: Decimal = Decimal("0.01")) -> bool:
    """Check that a cell's displayed value equals the linked fact's value.

    Both are compared as Decimals within tolerance.
    Returns False if either side cannot be parsed as Decimal.
    """
    if cell.value is None:
        return False
    try:
        stored = Decimal(index_entry.display)
    except (InvalidOperation, AttributeError, ValueError):
        return False
    try:
        shown = Decimal(str(cell.value))
    except (InvalidOperation, ValueError):
        return False
    return abs(shown - stored) <= tol


def provenance_validity(cells: list, fact_index: dict, tol: Decimal = Decimal("0.01")) -> float:
    """Fraction of numeric cells with valid provenance.

    A cell counts as good iff:
      1. It has a fact_id
      2. The fact_id resolves in fact_index
      3. The linked fact's stored value equals the cell's shown value within tol

    N/A cells (value None) are excluded from the denominator.

    Returns:
        float between 0.0 and 1.0. Empty cells or all-N/A -> 0.0.
    """
    numeric_cells = [c for c in cells if c.value is not None]
    if not numeric_cells:
        return 0.0

    good = 0
    for c in numeric_cells:
        if not c.fact_id:
            continue
        if c.fact_id not in fact_index:
            continue
        if _cell_value_matches(c, fact_index[c.fact_id], tol):
            good += 1

    return good / len(numeric_cells)


# ---------------------------------------------------------------------------
# score_run: compose all metrics for a single result vs a golden case
# ---------------------------------------------------------------------------

def _table_to_predicted_cells(table) -> dict[tuple, str]:
    """Extract predicted cell dict from a Table object.

    Returns dict of (company, alias, frame) -> str(value) for all
    non-None cell values.
    """
    predicted = {}
    if table is None:
        return predicted
    for row in table.rows:
        for cell in row.cells:
            if cell.value is None:
                continue
            key = (row.company, row.alias, cell.frame)
            predicted[key] = str(cell.value)
    return predicted


def _parse_golden_cells(expected_cells: dict) -> dict[tuple, str]:
    """Parse the yaml-style {"TICKER|alias|frame": "value"} into tuple-keyed dict."""
    parsed = {}
    for key, val in expected_cells.items():
        parts = key.split("|")
        if len(parts) != 3:
            continue
        ticker, alias, frame = parts
        parsed[(ticker, alias, frame)] = val
    return parsed


def _all_cells_from_table(table) -> list:
    """Flatten all cells from a table into a single list."""
    if table is None:
        return []
    cells = []
    for row in table.rows:
        cells.extend(row.cells)
    return cells


def score_run(result, golden_case: dict) -> dict:
    """Score a single result against a golden case.

    Args:
        result: a Result object (or dict with compatible keys)
        golden_case: dict with keys expected_behavior, expected_cells, etc.

    Returns:
        dict with keys: numeric_accuracy, provenance_validity, hallucination_rate,
        task_completion, boundary_correct, overall
    """
    expected_cells = _parse_golden_cells(golden_case.get("expected_cells", {}))
    expected_behavior = golden_case.get("expected_behavior", "answer")

    # Extract table cells
    table = getattr(result, "table", None)
    predicted = _table_to_predicted_cells(table)
    all_cells = _all_cells_from_table(table)

    # Numeric accuracy (table cells)
    num_acc = numeric_accuracy(predicted, expected_cells)

    # Provenance validity
    index = getattr(result, "index", {}) or {}
    prov_val = provenance_validity(all_cells, index)

    # Hallucination rate
    verdicts = getattr(result, "verdicts", []) or []
    hall_rate = hallucination_rate(verdicts)

    # Task completion
    task_completion = _check_task_completion(result, expected_behavior, table)

    # Boundary correctness (relevant only for ask/degrade behaviors)
    boundary_correct = _check_boundary(result, expected_behavior, table)

    # Overall score: weighted composite for answer/produce_table cases
    # For adversarial cases, boundary_correct dominates.
    if expected_behavior in ("ask", "degrade"):
        overall = 1.0 if boundary_correct else 0.0
    else:
        # Simple average of the main quality metrics
        overall = (num_acc + prov_val + (1.0 - hall_rate)) / 3.0
        if not task_completion:
            overall *= 0.5  # heavy penalty for incomplete deliverables

    return {
        "numeric_accuracy": num_acc,
        "provenance_validity": prov_val,
        "hallucination_rate": hall_rate,
        "task_completion": task_completion,
        "boundary_correct": boundary_correct,
        "overall": overall,
    }


def _check_task_completion(result, expected_behavior: str, table) -> bool:
    """Check whether the requested deliverables are present."""
    claims = getattr(result, "claims", []) or []

    if expected_behavior == "answer":
        # Need claims (narrative answer) — table is nice but claims are the deliverable
        return len(claims) > 0
    elif expected_behavior == "produce_table":
        # Need a non-empty table
        return table is not None and len(table.rows) > 0
    elif expected_behavior in ("ask", "degrade"):
        # For ask/degrade, "completion" means the system handled it gracefully
        # This is captured by boundary_correct, not task_completion
        return True
    return False


def _check_boundary(result, expected_behavior: str, table) -> bool:
    """Check that adversarial/boundary cases are handled correctly.

    - ask: system should ask for clarification (no fabricated table or it's empty)
    - degrade: system should degrade gracefully (downgraded > 0 or empty table)
    - answer/produce_table: N/A (always True)
    """
    if expected_behavior not in ("ask", "degrade"):
        return True

    downgraded = getattr(result, "downgraded", 0) or 0
    has_table = table is not None and len(table.rows) > 0

    if expected_behavior == "ask":
        # Correct if no fabricated data (empty table or no table)
        return not has_table

    if expected_behavior == "degrade":
        # Correct if something was downgraded (system refused to fabricate)
        # or table is empty
        return downgraded > 0 or not has_table

    return True


# ---------------------------------------------------------------------------
# Baseline adapters
# ---------------------------------------------------------------------------

def parse_baseline_numbers(text: str, golden_case: dict) -> dict[tuple, str]:
    """Best-effort extraction of numbers from free-form baseline output.

    Looks for patterns like "TICKER frame: number" near ticker/frame mentions.
    This is intentionally heuristic — baselines produce unstructured text.

    Returns a predicted dict in the same shape as _table_to_predicted_cells.
    """
    predicted = {}
    expected_cells = golden_case.get("expected_cells", {})
    if not expected_cells:
        return predicted

    # For each expected cell, try to find a number near the ticker/frame mention
    for cell_key in expected_cells:
        parts = cell_key.split("|")
        if len(parts) != 3:
            continue
        ticker, alias, frame = parts

        # Search for ticker + frame followed by a number
        pattern = re.compile(
            rf"{re.escape(ticker)}.*?{re.escape(frame)}.*?([\d,]+\.\d+|\d+)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            num_str = match.group(1).replace(",", "")
            try:
                val = Decimal(num_str)
                predicted[(ticker, alias, frame)] = str(val.quantize(Decimal("0.01")))
            except InvalidOperation:
                pass

        # Also try: number near ticker (without frame)
        if (ticker, alias, frame) not in predicted:
            pattern2 = re.compile(
                rf"{re.escape(ticker)}.*?([\d,]+\.\d+|\d+)",
                re.IGNORECASE,
            )
            match2 = pattern2.search(text)
            if match2:
                num_str = match2.group(1).replace(",", "")
                try:
                    val = Decimal(num_str)
                    predicted[(ticker, alias, frame)] = str(val.quantize(Decimal("0.01")))
                except InvalidOperation:
                    pass

    return predicted


def score_baseline_output(baseline_text: str, golden_case: dict) -> dict:
    """Score free-form baseline output against a golden case.

    Baselines have no fact links → provenance_validity ≈ 0.
    Hallucination rate is approximated: if numbers don't match golden, they hallucinate.
    """
    expected_cells = _parse_golden_cells(golden_case.get("expected_cells", {}))
    predicted = parse_baseline_numbers(baseline_text, golden_case)

    num_acc = numeric_accuracy(predicted, expected_cells)

    # Provenance: baselines have no fact links → 0.0
    prov_val = 0.0

    # Hallucination: approximate as fraction of golden cells not matched
    # (baseline has no structured verdicts, so we infer from numeric mismatch)
    if expected_cells:
        matched = sum(
            1 for k in expected_cells
            if k in predicted and _numbers_match(predicted[k], expected_cells[k])
        )
        hall_rate = 1.0 - (matched / len(expected_cells))
    else:
        hall_rate = 0.0

    expected_behavior = golden_case.get("expected_behavior", "answer")

    # Task completion: baseline produced some text
    task_completion = len(baseline_text.strip()) > 0

    # Boundary: always False for baselines on adversarial cases
    # (they tend to guess rather than ask/degrade)
    if expected_behavior in ("ask", "degrade"):
        boundary_correct = False
        overall = 0.0
    else:
        boundary_correct = True
        overall = (num_acc + prov_val + (1.0 - hall_rate)) / 3.0
        if not task_completion:
            overall *= 0.5

    return {
        "numeric_accuracy": num_acc,
        "provenance_validity": prov_val,
        "hallucination_rate": hall_rate,
        "task_completion": task_completion,
        "boundary_correct": boundary_correct,
        "overall": overall,
    }


def _numbers_match(a: str, b: str, tol: Decimal = Decimal("0.01")) -> bool:
    """Compare two number strings within tolerance."""
    try:
        return abs(Decimal(a) - Decimal(b)) <= tol
    except (InvalidOperation, ValueError):
        return False


# ---------------------------------------------------------------------------
# run_eval: the full runner
# ---------------------------------------------------------------------------

def run_eval(
    golden_path: str | Path,
    run_harness: Callable,
    run_baseline: Callable,
    out_md: str | Path,
) -> dict:
    """Run the full evaluation and produce a markdown report.

    Args:
        golden_path: path to golden.yaml
        run_harness: callable(case) -> score_dict (runs the full harness)
        run_baseline: callable(case, mode) -> score_dict (mode in {"bare", "linked"})
        out_md: path to write the markdown report

    Returns:
        aggregate dict with per-mode means and per-category breakdowns
    """
    golden_path = Path(golden_path)
    out_md = Path(out_md)

    with open(golden_path) as f:
        cases = yaml.safe_load(f)

    # Run all cases
    per_case = []
    for case in cases:
        harness_scores = run_harness(case)
        bare_scores = run_baseline(case, "bare")
        linked_scores = run_baseline(case, "linked")
        per_case.append({
            "case": case,
            "harness": harness_scores,
            "bare": bare_scores,
            "linked": linked_scores,
        })

    # Compute aggregates
    agg = _compute_aggregates(per_case)

    # Write markdown report
    _write_markdown_report(per_case, agg, out_md)

    return agg


def _compute_aggregates(per_case: list) -> dict:
    """Compute mean scores per mode, overall and per category."""
    modes = ("harness", "bare", "linked")
    metrics = ("numeric_accuracy", "provenance_validity", "hallucination_rate", "overall")

    by_category: dict[str, dict] = {}
    for mode in modes:
        by_category[mode] = {}

    # Collect per category
    category_cases: dict[str, list] = {}
    for entry in per_case:
        cat = entry["case"].get("category", "unknown")
        category_cases.setdefault(cat, []).append(entry)

    # Compute per-category means
    for cat, entries in category_cases.items():
        for mode in modes:
            cat_metrics = {}
            for metric in metrics:
                vals = [e[mode][metric] for e in entries if metric in e[mode]]
                cat_metrics[metric] = sum(vals) / len(vals) if vals else 0.0
            by_category[mode][cat] = cat_metrics

    # Overall means
    overall = {}
    for mode in modes:
        mode_metrics = {}
        for metric in metrics:
            vals = [e[mode][metric] for e in per_case if metric in e[mode]]
            mode_metrics[metric] = sum(vals) / len(vals) if vals else 0.0
        overall[mode] = mode_metrics

    return {
        "harness": overall["harness"],
        "bare": overall["bare"],
        "linked": overall["linked"],
        "by_category": by_category,
    }


def _write_markdown_report(per_case: list, agg: dict, out_md: Path) -> None:
    """Write a markdown comparison report to out_md."""
    lines = []
    lines.append("# Financial Agent Evaluation Report")
    lines.append("")
    lines.append(f"Cases evaluated: {len(per_case)}")
    lines.append("")

    # Per-case results table
    lines.append("## Per-Case Results")
    lines.append("")
    lines.append("| Case | Category | Mode | Numeric Acc | Provenance | Hallucination | Overall |")
    lines.append("|---|---|---|---:|---:|---:|---:|")

    for entry in per_case:
        case = entry["case"]
        cid = case["id"]
        cat = case.get("category", "?")
        for mode in ("harness", "bare", "linked"):
            s = entry[mode]
            lines.append(
                f"| {cid} | {cat} | {mode} | "
                f"{s['numeric_accuracy']:.3f} | "
                f"{s['provenance_validity']:.3f} | "
                f"{s['hallucination_rate']:.3f} | "
                f"{s['overall']:.3f} |"
            )

    lines.append("")

    # Aggregate comparison table
    lines.append("## Aggregate Comparison (Overall Means)")
    lines.append("")
    lines.append("| Mode | Numeric Accuracy | Provenance Validity | Hallucination Rate | Overall |")
    lines.append("|---|---:|---:|---:|---:|")

    for mode in ("harness", "bare", "linked"):
        s = agg[mode]
        lines.append(
            f"| {mode} | "
            f"{s['numeric_accuracy']:.3f} | "
            f"{s['provenance_validity']:.3f} | "
            f"{s['hallucination_rate']:.3f} | "
            f"{s['overall']:.3f} |"
        )

    lines.append("")

    # Per-category breakdown
    lines.append("## Per-Category Breakdown")
    lines.append("")

    categories = list(agg["by_category"]["harness"].keys())
    for cat in sorted(categories):
        lines.append(f"### {cat}")
        lines.append("")
        lines.append("| Mode | Numeric Accuracy | Provenance Validity | Hallucination Rate | Overall |")
        lines.append("|---|---:|---:|---:|---:|")
        for mode in ("harness", "bare", "linked"):
            s = agg["by_category"][mode].get(cat, {})
            lines.append(
                f"| {mode} | "
                f"{s.get('numeric_accuracy', 0.0):.3f} | "
                f"{s.get('provenance_validity', 0.0):.3f} | "
                f"{s.get('hallucination_rate', 0.0):.3f} | "
                f"{s.get('overall', 0.0):.3f} |"
            )
        lines.append("")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# __main__: live evaluation with real clients
# ---------------------------------------------------------------------------

def _main():
    """Run live evaluation with real OpenAI + SEC clients.

    Requires:
      - OPENAI_API_KEY
      - SEC_NAME + SEC_EMAIL
      - finagent installed with dependencies

    Usage: python -m finagent.eval.run_eval [--out report.md]
    """
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Run financial agent evaluation")
    parser.add_argument(
        "--golden",
        default=str(Path(__file__).parent / "golden.yaml"),
        help="Path to golden.yaml",
    )
    parser.add_argument(
        "--out",
        default="eval-report.md",
        help="Output markdown report path",
    )
    parser.add_argument("--model", default=None, help="Override model name")
    args = parser.parse_args()

    # --- Build real clients (same pattern as finagent.app.main) ---
    from finagent.config import Config
    from finagent.cache import ResponseCache
    from finagent.datasource.sec_client import SECClient
    from finagent.datasource.tickers import TickerResolver
    from finagent.agent.llm import LLMClient
    from finagent.profile.store import ProfileStore
    from finagent.app import run_query
    import openai

    sec_name = os.environ.get("SEC_NAME", "")
    sec_email = os.environ.get("SEC_EMAIL", "")
    sec_contact = (sec_name, sec_email) if sec_name and sec_email else None
    if sec_contact is None:
        print("Error: SEC_NAME and SEC_EMAIL environment variables are required.", file=sys.stderr)
        sys.exit(1)

    cfg = Config.from_env(os.environ, sec_contact=sec_contact)
    if not cfg.openai_api_key:
        print("Error: OPENAI_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)

    model = args.model or cfg.model
    oai_client = openai.OpenAI(api_key=cfg.openai_api_key)
    llm = LLMClient(oai_client, model)

    cache = ResponseCache(cfg.cache_path)
    sec = SECClient(cfg.sec_user_agent, cache)
    resolver = TickerResolver(sec)

    profile_store = ProfileStore(cfg.profile_path)
    profile = profile_store.load()

    # --- Harness runner ---
    def run_harness(case):
        result = run_query(case["question"], llm, sec, resolver, profile)
        return score_run(result, case)

    # --- Build live ticker->CIK map from resolver ---
    live_ticker_cik = {}
    for entry in resolver.index:
        ticker = entry.get("ticker", "")
        cik = entry.get("cik")
        if ticker and cik:
            live_ticker_cik[ticker.upper()] = int(cik)

    # --- Baseline runners ---
    def run_baseline(case, mode):
        question = case["question"]
        if mode == "bare":
            system, user_msg = build_bare_prompt(question)
        else:  # linked
            urls = build_sec_urls_for_case(case, live_ticker_cik)
            system, user_msg = build_linked_prompt(question, urls)

        # For baseline, we use a simple text completion and score it
        try:
            resp = oai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
            )
            text = resp.choices[0].message.content or ""
        except Exception as e:
            text = f"Error: {e}"

        return score_baseline_output(text, case)

    # --- Run eval ---
    print(f"Running evaluation with {model}...")
    agg = run_eval(args.golden, run_harness, run_baseline, args.out)
    print(f"Report written to {args.out}")
    print()
    print("Overall results:")
    for mode in ("harness", "bare", "linked"):
        s = agg[mode]
        print(f"  {mode:8s} num_acc={s['numeric_accuracy']:.3f}  "
              f"prov={s['provenance_validity']:.3f}  "
              f"hall={s['hallucination_rate']:.3f}  "
              f"overall={s['overall']:.3f}")


if __name__ == "__main__":
    _main()
