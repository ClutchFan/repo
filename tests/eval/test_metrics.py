"""Tests for eval scoring functions and runner.

TDD: these tests should fail first, then pass after implementing run_eval.py.
"""

import json
import pathlib
from decimal import Decimal
from datetime import date

import pytest
import yaml

from finagent.narrative.verifier import Verdict
from finagent.output.table import Table, TableRow, Cell
from finagent.models import Fact, Provenance, make_fact_id, Company, Claim
from finagent.app import Result
from finagent.eval.fixtures import display_value, RAW_VALUES, ALIAS_TO_CONCEPT


# ---------------------------------------------------------------------------
# Import target module (will fail until implemented)
# ---------------------------------------------------------------------------

from finagent.eval.run_eval import (
    numeric_accuracy,
    hallucination_rate,
    provenance_validity,
    score_run,
    run_eval,
    _cell_value_matches,
)


# ---------------------------------------------------------------------------
# Test 1: numeric_accuracy basic (from brief)
# ---------------------------------------------------------------------------

def test_numeric_accuracy_basic():
    g = {("A", "revenue", "CY2024Q1"): "119580.00"}
    assert numeric_accuracy({("A", "revenue", "CY2024Q1"): "119580.00"}, g) == 1.0
    assert numeric_accuracy({("A", "revenue", "CY2024Q1"): "999.00"}, g) == 0.0


def test_numeric_accuracy_empty_golden():
    """Empty golden → 0.0 per spec."""
    assert numeric_accuracy({}, {}) == 0.0
    assert numeric_accuracy({("A", "revenue", "CY2024Q1"): "100"}, {}) == 0.0


def test_numeric_accuracy_partial_match():
    g = {
        ("A", "revenue", "CY2024Q1"): "100.00",
        ("A", "revenue", "CY2024Q2"): "200.00",
    }
    pred = {
        ("A", "revenue", "CY2024Q1"): "100.00",
        ("A", "revenue", "CY2024Q2"): "999.00",
    }
    assert numeric_accuracy(pred, g) == 0.5


def test_numeric_accuracy_unparseable_prediction_counts_as_mismatch():
    """If a prediction cannot be parsed as Decimal, it counts as mismatch.
    Do NOT silently skip golden keys."""
    g = {("A", "revenue", "CY2024Q1"): "119580.00"}
    assert numeric_accuracy({("A", "revenue", "CY2024Q1"): "N/A"}, g) == 0.0
    assert numeric_accuracy({("A", "revenue", "CY2024Q1"): "not a number"}, g) == 0.0


def test_numeric_accuracy_tolerance():
    g = {("A", "revenue", "CY2024Q1"): "100.00"}
    # Within 0.01 tolerance
    assert numeric_accuracy({("A", "revenue", "CY2024Q1"): "100.005"}, g, tol=Decimal("0.01")) == 1.0
    # Outside tolerance
    assert numeric_accuracy({("A", "revenue", "CY2024Q1"): "100.02"}, g, tol=Decimal("0.01")) == 0.0


def test_numeric_accuracy_missing_pred_key():
    """Missing predicted key → mismatch."""
    g = {
        ("A", "revenue", "CY2024Q1"): "100.00",
        ("A", "revenue", "CY2024Q2"): "200.00",
    }
    pred = {("A", "revenue", "CY2024Q1"): "100.00"}
    assert numeric_accuracy(pred, g) == 0.5


# ---------------------------------------------------------------------------
# Test 2: hallucination_rate basic (from brief)
# ---------------------------------------------------------------------------

def test_hallucination_rate_basic():
    vs = [Verdict("a", True, ""), Verdict("b", False, "x")]
    assert hallucination_rate(vs) == 0.5


def test_hallucination_rate_empty():
    assert hallucination_rate([]) == 0.0


def test_hallucination_rate_all_ok():
    vs = [Verdict("a", True, ""), Verdict("b", True, "")]
    assert hallucination_rate(vs) == 0.0


def test_hallucination_rate_all_failed():
    vs = [Verdict("a", False, "x"), Verdict("b", False, "y")]
    assert hallucination_rate(vs) == 1.0


# ---------------------------------------------------------------------------
# Test 3: provenance_validity
# ---------------------------------------------------------------------------

def _make_index_entry(display: str):
    """Helper: create an index entry object with .display attribute."""
    return type("E", (), {"display": display})()


def test_provenance_validity_all_good():
    cells = [
        Cell("CY2024Q1", Decimal("100.00"), "f1"),
        Cell("CY2024Q2", Decimal("200.00"), "f2"),
    ]
    index = {
        "f1": _make_index_entry("100.00"),
        "f2": _make_index_entry("200.00"),
    }
    assert provenance_validity(cells, index) == 1.0


def test_provenance_validity_value_mismatch():
    """A cell with fact_id that resolves but whose stored value differs from
    the cell value should count as bad. This is the stricter spec-faithful check."""
    cells = [
        Cell("CY2024Q1", Decimal("100.00"), "f1"),
    ]
    # index has a different value than what the cell shows
    index = {"f1": _make_index_entry("200.00")}
    assert provenance_validity(cells, index) == 0.0


def test_provenance_validity_missing_fact_id():
    """Cell with fact_id not in index → bad."""
    cells = [Cell("CY2024Q1", Decimal("100.00"), "missing_id")]
    index = {"other_id": _make_index_entry("100.00")}
    assert provenance_validity(cells, index) == 0.0


def test_provenance_validity_no_fact_id_cells_excluded_from_denominator():
    """N/A cells (value None, no fact_id) are excluded from the denominator."""
    cells = [
        Cell("CY2024Q1", Decimal("100.00"), "f1"),
        Cell("CY2024Q2", None, None, "N/A: not reported"),
    ]
    index = {"f1": _make_index_entry("100.00")}
    # denominator = 1 (only the numeric cell), all good → 1.0
    assert provenance_validity(cells, index) == 1.0


def test_provenance_validity_empty_cells():
    assert provenance_validity([], {}) == 0.0


def test_provenance_validity_all_na_cells():
    """All cells are N/A → denominator = 0 → 0.0."""
    cells = [
        Cell("CY2024Q1", None, None, "N/A"),
        Cell("CY2024Q2", None, None, "N/A"),
    ]
    assert provenance_validity(cells, {}) == 0.0


def test_cell_value_matches_helper():
    """_cell_value_matches: compare cell value to index display string within tol."""
    cell = Cell("CY2024Q1", Decimal("119580.00"), "f1")
    entry = _make_index_entry("119580.00")
    assert _cell_value_matches(cell, entry, Decimal("0.01")) is True

    # Mismatch
    entry2 = _make_index_entry("99999.00")
    assert _cell_value_matches(cell, entry2, Decimal("0.01")) is False

    # Within tolerance
    entry3 = _make_index_entry("119580.005")
    assert _cell_value_matches(cell, entry3, Decimal("0.01")) is True


# ---------------------------------------------------------------------------
# Test 4: score_run on a scripted result
# ---------------------------------------------------------------------------

def _make_scripted_result():
    """Build a minimal Result with one table row and some verdicts.

    Uses the fixtures AAPL revenue CY2024Q1 value for consistency.
    """
    from finagent.eval.fixtures import build_facts, RAW_VALUES, COMPANIES

    raw_facts = build_facts("AAPL", ["revenue"], ["CY2024Q1"])

    # Build table
    cell = Cell("CY2024Q1", Decimal("119580.00"), raw_facts[0].fact_id)
    row = TableRow("AAPL", "revenue", "millions", (cell,))
    table = Table(("CY2024Q1",), (row,))

    # Build index from facts
    from finagent.narrative.summarizer import build_evidence_bundle
    _, index = build_evidence_bundle(raw_facts, [])

    # Verdicts: one ok, one failed
    verdicts = [
        Verdict("c1", True, "ok"),
        Verdict("c2", False, "bad number"),
    ]

    claims = [
        Claim("c1", "AAPL revenue was 119580.00M.", (raw_facts[0].fact_id,), "datapoint"),
        Claim("c2", "Made up 99999M number.", (raw_facts[0].fact_id,), "datapoint"),
    ]

    # Minimal plan (just enough for the test)
    from finagent.models import QueryPlan, LineItem, PeriodSpec
    plan = QueryPlan(
        companies=(Company("AAPL", COMPANIES["AAPL"]["cik"], "Apple Inc."),),
        line_items=(LineItem("revenue", ("us-gaap:Revenues",), "USD", "millions"),),
        periods=PeriodSpec("last_n_quarters", 1),
        outputs=("table",),
    )

    return Result(
        plan=plan,
        table=table,
        claims=claims,
        verdicts=verdicts,
        facts_by_company={},
        index=index,
        downgraded=0,
    )


def test_score_run_basic():
    result = _make_scripted_result()
    golden_case = {
        "id": "single_01",
        "category": "single",
        "expected_behavior": "answer",
        "expected_cells": {
            "AAPL|revenue|CY2024Q1": "119580.00",
        },
    }
    scores = score_run(result, golden_case)

    # Numeric accuracy: one cell matches → 1.0
    assert scores["numeric_accuracy"] == 1.0
    # Hallucination rate: 1/2 failed → 0.5
    assert scores["hallucination_rate"] == 0.5
    # Provenance validity: one cell, fact_id matches, value matches → 1.0
    assert scores["provenance_validity"] == 1.0
    # Task completion: table non-empty + answer behavior → True
    assert scores["task_completion"] is True
    # Should have overall key
    assert "overall" in scores


def test_score_run_numeric_mismatch():
    result = _make_scripted_result()
    golden_case = {
        "id": "single_01",
        "category": "single",
        "expected_behavior": "answer",
        "expected_cells": {
            "AAPL|revenue|CY2024Q1": "99999.00",  # wrong expected value
        },
    }
    scores = score_run(result, golden_case)
    assert scores["numeric_accuracy"] == 0.0


def test_score_run_boundary_ask():
    """ask behavior: check that AmbiguousTicker is surfaced or no fabricated table."""
    result = _make_scripted_result()
    # Override with empty table for an ask case
    result.table = Table((), ())
    golden_case = {
        "id": "adv_01",
        "category": "adversarial",
        "expected_behavior": "ask",
        "expected_cells": {},
    }
    scores = score_run(result, golden_case)
    assert "boundary_correct" in scores
    # For ask with no table produced: boundary_correct should be True
    # (no fabricated data = correct behavior for ambiguous query)
    assert scores["boundary_correct"] is True


def test_score_run_boundary_degrade():
    """degrade behavior: downgraded > 0 means system correctly degraded."""
    result = _make_scripted_result()
    result.downgraded = 2
    golden_case = {
        "id": "adv_02",
        "category": "adversarial",
        "expected_behavior": "degrade",
        "expected_cells": {},
    }
    scores = score_run(result, golden_case)
    assert scores["boundary_correct"] is True


# ---------------------------------------------------------------------------
# Test 5: golden.yaml ↔ fixtures.py consistency
# ---------------------------------------------------------------------------

def _load_golden():
    yaml_path = pathlib.Path(__file__).parent.parent.parent / "finagent" / "eval" / "golden.yaml"
    with open(yaml_path) as f:
        return yaml.safe_load(f)


def test_golden_yaml_has_15_cases():
    cases = _load_golden()
    assert len(cases) == 15


def test_golden_yaml_category_counts():
    cases = _load_golden()
    from collections import Counter
    counts = Counter(c["category"] for c in cases)
    assert counts["single"] == 3
    assert counts["trend"] == 3
    assert counts["multi_company"] == 4
    assert counts["narrative"] == 3
    assert counts["adversarial"] == 2


def test_golden_numeric_values_match_fixtures():
    """Every expected_cells value in golden.yaml must match the fixture's
    display_value for that ticker/alias/frame triple.

    This is the bidirectional consistency test: yaml numeric values trace to
    fixture constants.
    """
    cases = _load_golden()
    mismatches = []
    for case in cases:
        for key, expected in case.get("expected_cells", {}).items():
            parts = key.split("|")
            assert len(parts) == 3, f"Bad cell key format: {key}"
            ticker, alias, frame = parts
            actual = display_value(ticker, alias, frame)
            if actual != expected:
                mismatches.append(f"{case['id']} {key}: yaml={expected} fixture={actual}")
    assert not mismatches, f"YAML values don't match fixtures:\n" + "\n".join(mismatches)


def test_all_fixture_companies_in_golden():
    """All four covered tickers appear in at least one golden case."""
    cases = _load_golden()
    tickers = set()
    for case in cases:
        for key in case.get("expected_cells", {}):
            tickers.add(key.split("|")[0])
    assert "AAPL" in tickers
    assert "MSFT" in tickers
    assert "NVDA" in tickers
    assert "GOOG" in tickers


# ---------------------------------------------------------------------------
# Test 6: run_eval produces markdown report
# ---------------------------------------------------------------------------

def test_run_eval_produces_markdown(tmp_path):
    """run_eval with scripted runners should produce a markdown file with
    harness/bare/linked rows and aggregate means."""
    import tempfile

    # Create a temp golden yaml with one simple case
    golden = [
        {
            "id": "single_01",
            "category": "single",
            "question": "What was AAPL revenue for CY2024Q1?",
            "expected_behavior": "answer",
            "expected_cells": {"AAPL|revenue|CY2024Q1": "119580.00"},
        },
    ]
    golden_path = tmp_path / "golden.yaml"
    with open(golden_path, "w") as f:
        yaml.dump(golden, f)

    # Scripted harness runner that returns a result dict
    def fake_run_harness(case):
        return {
            "numeric_accuracy": 1.0,
            "provenance_validity": 1.0,
            "hallucination_rate": 0.0,
            "task_completion": True,
            "boundary_correct": True,
            "overall": (1.0 + 1.0 + 1.0) / 3.0,
        }

    # Scripted baseline runner
    def fake_run_baseline(case, mode):
        # bare mode: somewhat wrong numbers, no provenance
        if mode == "bare":
            return {
                "numeric_accuracy": 0.5,
                "provenance_validity": 0.0,
                "hallucination_rate": 0.3,
                "task_completion": True,
                "boundary_correct": False,
                "overall": (0.5 + 0.0 + 0.7) / 3.0,
            }
        else:  # linked mode: better numbers but still no provenance
            return {
                "numeric_accuracy": 0.8,
                "provenance_validity": 0.0,
                "hallucination_rate": 0.2,
                "task_completion": True,
                "boundary_correct": False,
                "overall": (0.8 + 0.0 + 0.8) / 3.0,
            }

    out_md = tmp_path / "report.md"
    agg = run_eval(golden_path, fake_run_harness, fake_run_baseline, out_md)

    # File was created
    assert out_md.exists()
    content = out_md.read_text()

    # Contains the three comparison rows
    assert "harness" in content.lower()
    assert "bare" in content.lower()
    assert "linked" in content.lower()

    # Contains per-case table
    assert "single_01" in content

    # Contains aggregate means
    assert "aggregate" in content.lower() or "overall" in content.lower()

    # agg dict has the right structure
    assert "harness" in agg
    assert "bare" in agg
    assert "linked" in agg
    assert "numeric_accuracy" in agg["harness"]
    assert agg["harness"]["numeric_accuracy"] == 1.0
    assert agg["bare"]["numeric_accuracy"] == 0.5
    assert agg["linked"]["numeric_accuracy"] == 0.8


def test_run_eval_multiple_categories_aggregates(tmp_path):
    """run_eval should compute per-category aggregates and overall."""
    golden = [
        {
            "id": "single_01",
            "category": "single",
            "question": "Q1",
            "expected_behavior": "answer",
            "expected_cells": {"AAPL|revenue|CY2024Q1": "100.00"},
        },
        {
            "id": "trend_01",
            "category": "trend",
            "question": "Q2",
            "expected_behavior": "produce_table",
            "expected_cells": {"AAPL|revenue|CY2024Q1": "100.00"},
        },
    ]
    golden_path = tmp_path / "golden.yaml"
    with open(golden_path, "w") as f:
        yaml.dump(golden, f)

    call_log = []

    def fake_run_harness(case):
        call_log.append(("harness", case["id"]))
        return {
            "numeric_accuracy": 1.0,
            "provenance_validity": 0.9,
            "hallucination_rate": 0.1,
            "task_completion": True,
            "boundary_correct": True,
            "overall": (1.0 + 0.9 + 0.9) / 3.0,
        }

    def fake_run_baseline(case, mode):
        call_log.append((mode, case["id"]))
        return {
            "numeric_accuracy": 0.5,
            "provenance_validity": 0.0,
            "hallucination_rate": 0.5,
            "task_completion": True,
            "boundary_correct": False,
            "overall": (0.5 + 0.0 + 0.5) / 3.0,
        }

    out_md = tmp_path / "report.md"
    agg = run_eval(golden_path, fake_run_harness, fake_run_baseline, out_md)

    # Harness was called for each case
    harness_calls = [c for c in call_log if c[0] == "harness"]
    assert len(harness_calls) == 2

    # Both baselines were called for each case
    bare_calls = [c for c in call_log if c[0] == "bare"]
    linked_calls = [c for c in call_log if c[0] == "linked"]
    assert len(bare_calls) == 2
    assert len(linked_calls) == 2

    # Per-category aggregations exist
    assert "by_category" in agg
    assert "single" in agg["by_category"]["harness"]
    assert "trend" in agg["by_category"]["harness"]

    # Overall means
    assert agg["harness"]["numeric_accuracy"] == 1.0
    assert agg["bare"]["numeric_accuracy"] == 0.5
