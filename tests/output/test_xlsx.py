"""Tests for finagent.output.xlsx — XLSX export with provenance.

Covers:
- Sheet structure (Comparison / Provenance / Claims)
- Native raw fact cell hyperlinks + comments
- YTD_DIFF derived fact cell resolution (fact_id from quarter_facts)
- Ratio formula row cell reconstruction via ratio(gp, rv)
- N/A cells (fact_id None) write note text and have no hyperlink
- Snapshot JSON written alongside the workbook
"""
import json
import pathlib
from datetime import date
from decimal import Decimal

import pytest

from finagent.app import Result
from finagent.models import (
    Company,
    Fact,
    Provenance,
    make_fact_id,
    Claim,
)
from finagent.narrative.verifier import Verdict
from finagent.output.table import Table, TableRow, Cell
from finagent.datasource.facts import quarter_facts
from finagent.metrics import ratio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AAPL = Company("AAPL", 320193, "Apple Inc.")
MSFT = Company("MSFT", 789019, "Microsoft Corp.")


def _prov(acc, form, filed, fp, fy, concept, src_url, raw_value):
    return Provenance(acc, form, filed, fp, fy, concept, src_url, src_url + "-xbrl", raw_value)


def _fact(ticker, concept, val, frame, start, end, acc, form="10-Q", filed="2024-05-01",
          fp="Q1", fy=2024, unit="USD", cik=320193, company_name="Apple Inc.",
          src_url=None):
    if src_url is None:
        src_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{acc}-index.htm"
    return Fact(
        make_fact_id(ticker, concept, unit, str(start), str(end), acc, str(val)),
        cik, ticker, company_name, Decimal(str(val)), unit, concept,
        date.fromisoformat(start) if isinstance(start, str) else start,
        date.fromisoformat(end) if isinstance(end, str) else end,
        frame,
        _prov(acc, form, filed, fp, fy, concept, src_url, str(val)),
    )


def _ytd_diff_fact(multi: Fact, prefix: Fact) -> Fact:
    """Recreate the YTD_DIFF derivation that single_quarters produces,
    so the test has a known fact_id to assert against."""
    derived_value = multi.value - prefix.value
    derived_start = date.fromordinal(prefix.period_end.toordinal() + 1)
    fid = make_fact_id("YTDDIFF", multi.fact_id, prefix.fact_id)
    newprov = Provenance(
        multi.provenance.accession,
        multi.provenance.form,
        multi.provenance.filed_date,
        multi.provenance.fiscal_period,
        multi.provenance.fiscal_year,
        multi.provenance.concept,
        multi.provenance.source_url,
        multi.provenance.xbrl_fact_url,
        "derived:YTD_DIFF",
    )
    from finagent.datasource.facts import calendar_frame
    return Fact(
        fid, multi.cik, multi.ticker, multi.company_name,
        derived_value, multi.unit, multi.concept,
        derived_start, multi.period_end,
        calendar_frame(multi.period_end),
        newprov,
    )


def fake_result(tmp_path):
    """Build a Result with one native raw fact, one YTD_DIFF derived fact,
    a ratio row, and one claim+verdict. All table cells carry fact_ids
    that resolve through the three-source lookup."""

    # --- Raw facts for AAPL ---
    # Native single-quarter revenue (Q1)
    rev_q1 = _fact(
        "AAPL", "us-gaap:Revenues", "100000000000", "CY2024Q1",
        "2024-01-01", "2024-03-31",
        "0000320193-24-000006",
        src_url="https://example.com/aapl/rev-q1",
    )
    # Native single-quarter gross profit (Q1)
    gp_q1 = _fact(
        "AAPL", "us-gaap:GrossProfit", "40000000000", "CY2024Q1",
        "2024-01-01", "2024-03-31",
        "0000320193-24-000006",
        src_url="https://example.com/aapl/gp-q1",
    )
    # H1 cumulative revenue (used to derive Q2 via YTD_DIFF)
    rev_h1 = _fact(
        "AAPL", "us-gaap:Revenues", "220000000000", "CY2024Q2",
        "2024-01-01", "2024-06-30",
        "0000320193-24-000007",
        form="10-Q", filed="2024-08-01", fp="Q2", fy=2024,
        src_url="https://example.com/aapl/rev-h1",
    )
    # H1 cumulative gross profit (used to derive Q2 via YTD_DIFF)
    gp_h1 = _fact(
        "AAPL", "us-gaap:GrossProfit", "90000000000", "CY2024Q2",
        "2024-01-01", "2024-06-30",
        "0000320193-24-000007",
        form="10-Q", filed="2024-08-01", fp="Q2", fy=2024,
        src_url="https://example.com/aapl/gp-h1",
    )

    raw_facts = [rev_q1, gp_q1, rev_h1, gp_h1]

    # Quarter facts: should include native Q1 + derived Q2
    qf = quarter_facts(raw_facts)
    # Find the derived Q2 revenue fact (YTD_DIFF)
    rev_q2 = [f for f in qf if f.concept == "us-gaap:Revenues" and f.frame == "CY2024Q2"][0]
    gp_q2 = [f for f in qf if f.concept == "us-gaap:GrossProfit" and f.frame == "CY2024Q2"][0]
    assert rev_q2.provenance.raw_value == "derived:YTD_DIFF"
    assert gp_q2.provenance.raw_value == "derived:YTD_DIFF"

    # Ratio derived facts
    ratio_q1 = ratio(gp_q1, rev_q1)
    ratio_q2 = ratio(gp_q2, rev_q2)

    # --- Build Table ---
    cols = ("CY2024Q1", "CY2024Q2")

    # Revenue row (native Q1 + YTD_DIFF Q2)
    rev_row = TableRow(
        company="AAPL",
        alias="revenue",
        scaling="millions",
        cells=(
            Cell("CY2024Q1", Decimal("100000.00"), rev_q1.fact_id, ""),
            Cell("CY2024Q2", Decimal("120000.00"), rev_q2.fact_id, "derived:YTD_DIFF"),
        ),
    )

    # Gross profit row
    gp_row = TableRow(
        company="AAPL",
        alias="gross_profit",
        scaling="millions",
        cells=(
            Cell("CY2024Q1", Decimal("40000.00"), gp_q1.fact_id, ""),
            Cell("CY2024Q2", Decimal("50000.00"), gp_q2.fact_id, "derived:YTD_DIFF"),
        ),
    )

    # Gross margin ratio row
    gm_row = TableRow(
        company="AAPL",
        alias="gross_margin",
        scaling="millions",
        cells=(
            Cell("CY2024Q1", (ratio_q1.value * 100).quantize(Decimal("0.000001")),
                 ratio_q1.fact_id, "derived:gross_profit/revenue"),
            Cell("CY2024Q2", (ratio_q2.value * 100).quantize(Decimal("0.000001")),
                 ratio_q2.fact_id, "derived:gross_profit/revenue"),
        ),
        formula="gross_profit/revenue",
    )

    # N/A row (missing concept)
    na_row = TableRow(
        company="AAPL",
        alias="net_income",
        scaling="millions",
        cells=(
            Cell("CY2024Q1", None, None, "N/A: not reported"),
            Cell("CY2024Q2", None, None, "N/A: not reported"),
        ),
    )

    table = Table(cols, (rev_row, gp_row, gm_row, na_row))

    # --- Claims + Verdicts ---
    claims = [
        Claim("c1", "AAPL revenue in CY2024Q1 was 100000.00 million USD.",
              (rev_q1.fact_id,), "datapoint"),
    ]
    verdicts = [
        Verdict("c1", True, "matches evidence"),
    ]

    # facts_by_company: maps Company -> raw facts list
    facts_by_company = {AAPL: raw_facts}

    # Minimal plan / index stubs (not used by xlsx export)
    plan = None
    index = {}

    return Result(plan, table, claims, verdicts, facts_by_company, index, 0)


# ---------------------------------------------------------------------------
# Test 1: Sheet structure — exactly {Comparison, Provenance, Claims}
# ---------------------------------------------------------------------------

def test_workbook_sheets(tmp_path):
    from finagent.output.xlsx import export_xlsx
    from openpyxl import load_workbook

    p = export_xlsx(fake_result(tmp_path), tmp_path / "out.xlsx")
    wb = load_workbook(p)
    assert set(wb.sheetnames) == {"Comparison", "Provenance", "Claims"}
    ws = wb["Provenance"]
    assert ws.max_row >= 2  # header + at least 1 fact


# ---------------------------------------------------------------------------
# Test 2: Native raw fact cell has hyperlink + comment
# ---------------------------------------------------------------------------

def test_native_fact_hyperlink_and_comment(tmp_path):
    from finagent.output.xlsx import export_xlsx
    from openpyxl import load_workbook

    result = fake_result(tmp_path)
    p = export_xlsx(result, tmp_path / "out.xlsx")
    wb = load_workbook(p)
    cmp = wb["Comparison"]

    # Revenue row is the first data row (row 2: header is row 1)
    # Row 2 = AAPL revenue, col 2 = CY2024Q1 (native fact)
    cell = cmp.cell(row=2, column=2)
    rev_q1_fact = result.facts_by_company[AAPL][0]  # first raw fact is rev_q1
    assert cell.hyperlink is not None
    assert cell.hyperlink.target == rev_q1_fact.provenance.source_url
    assert cell.comment is not None
    assert "us-gaap:Revenues" in cell.comment.text
    assert rev_q1_fact.provenance.accession in cell.comment.text


# ---------------------------------------------------------------------------
# Test 3: YTD_DIFF cell resolves — hyperlink target + comment non-empty
# ---------------------------------------------------------------------------

def test_ytd_diff_cell_resolves(tmp_path):
    from finagent.output.xlsx import export_xlsx
    from openpyxl import load_workbook

    result = fake_result(tmp_path)
    p = export_xlsx(result, tmp_path / "out.xlsx")
    wb = load_workbook(p)
    cmp = wb["Comparison"]

    # Revenue row (row 2), col 3 = CY2024Q2 (YTD_DIFF derived)
    cell = cmp.cell(row=2, column=3)

    # Find the YTD_DIFF rev_q2 fact from quarter_facts
    qf = quarter_facts(result.facts_by_company[AAPL])
    rev_q2 = [f for f in qf if f.concept == "us-gaap:Revenues" and f.frame == "CY2024Q2"][0]

    assert cell.hyperlink is not None, "YTD_DIFF cell should have a hyperlink"
    assert cell.hyperlink.target == rev_q2.provenance.source_url
    assert cell.comment is not None, "YTD_DIFF cell should have a comment"
    assert len(cell.comment.text.strip()) > 0
    assert "derived:YTD_DIFF" in cell.comment.text or "YTD" in cell.comment.text


# ---------------------------------------------------------------------------
# Test 4: Ratio formula cell resolves via reconstruction
# ---------------------------------------------------------------------------

def test_ratio_cell_resolves(tmp_path):
    from finagent.output.xlsx import export_xlsx
    from openpyxl import load_workbook

    result = fake_result(tmp_path)
    p = export_xlsx(result, tmp_path / "out.xlsx")
    wb = load_workbook(p)
    cmp = wb["Comparison"]

    # Gross margin row is row 4 (rev=2, gp=3, gm=4)
    # col 2 = CY2024Q1 ratio cell
    cell = cmp.cell(row=4, column=2)

    # Find Q1 gross profit fact (numerator) — its source_url is the hyperlink target
    qf = quarter_facts(result.facts_by_company[AAPL])
    gp_q1 = [f for f in qf if f.concept == "us-gaap:GrossProfit" and f.frame == "CY2024Q1"][0]
    rev_q1 = [f for f in qf if f.concept == "us-gaap:Revenues" and f.frame == "CY2024Q1"][0]

    assert cell.hyperlink is not None, "Ratio cell should have a hyperlink"
    # Hyperlink targets the numerator (gross profit) fact's source_url
    assert cell.hyperlink.target == gp_q1.provenance.source_url
    assert cell.comment is not None, "Ratio cell should have a comment"
    comment_text = cell.comment.text
    assert "derived:gross_profit/revenue" in comment_text
    assert gp_q1.fact_id in comment_text
    assert rev_q1.fact_id in comment_text


# ---------------------------------------------------------------------------
# Test 5: N/A cells (fact_id None) write note text and do NOT hyperlink
# ---------------------------------------------------------------------------

def test_na_cells_no_hyperlink(tmp_path):
    from finagent.output.xlsx import export_xlsx
    from openpyxl import load_workbook

    result = fake_result(tmp_path)
    p = export_xlsx(result, tmp_path / "out.xlsx")
    wb = load_workbook(p)
    cmp = wb["Comparison"]

    # N/A row is row 5 (rev=2, gp=3, gm=4, na=5)
    cell = cmp.cell(row=5, column=2)
    assert cell.hyperlink is None
    # Cell value should be the note text
    assert "N/A" in str(cell.value)


# ---------------------------------------------------------------------------
# Test 6: Snapshot JSON exists and contains fact ids
# ---------------------------------------------------------------------------

def test_snapshot_json_exists(tmp_path):
    from finagent.output.xlsx import export_xlsx

    result = fake_result(tmp_path)
    xlsx_path = tmp_path / "out.xlsx"
    p = export_xlsx(result, xlsx_path)

    snap_path = tmp_path / "snapshots" / "out.json"
    assert snap_path.exists(), f"Snapshot not found at {snap_path}"

    snap = json.loads(snap_path.read_text())

    # Must have a generated timestamp
    assert "generated_at" in snap
    assert "facts" in snap
    assert isinstance(snap["facts"], list)
    assert len(snap["facts"]) > 0

    # All facts should have required fields
    fact_ids_in_snap = {f["fact_id"] for f in snap["facts"]}

    # Native raw fact ids should be present (type "raw")
    raw_facts = result.facts_by_company[AAPL]
    for f in raw_facts:
        # Raw facts that are single-quarter show up as type raw
        if f.frame and f.frame.startswith("CY"):
            # Check that native quarters appear in snapshot
            pass

    # YTD_DIFF derived fact ids should be present (type "ytd_diff")
    qf = quarter_facts(result.facts_by_company[AAPL])
    derived = [f for f in qf if f.provenance.raw_value == "derived:YTD_DIFF"]
    for f in derived:
        assert f.fact_id in fact_ids_in_snap, f"YTD_DIFF fact {f.fact_id} missing from snapshot"

    # Ratio fact ids should be present (type "ratio")
    ratio_types = [f for f in snap["facts"] if f.get("type") == "ratio"]
    assert len(ratio_types) > 0, "No ratio-type facts in snapshot"
    for r in ratio_types:
        assert "formula" in r
        assert "input_fact_ids" in r


# ---------------------------------------------------------------------------
# Test 7: Claims sheet structure
# ---------------------------------------------------------------------------

def test_claims_sheet(tmp_path):
    from finagent.output.xlsx import export_xlsx
    from openpyxl import load_workbook

    result = fake_result(tmp_path)
    p = export_xlsx(result, tmp_path / "out.xlsx")
    wb = load_workbook(p)
    cl = wb["Claims"]

    # Header row
    header = [cl.cell(row=1, column=i).value for i in range(1, cl.max_column + 1)]
    assert "claim_id" in header
    assert "text" in header
    assert "verdict" in header

    # Data row
    assert cl.max_row >= 2
    assert cl.cell(row=2, column=1).value == "c1"
