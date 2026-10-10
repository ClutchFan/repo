from datetime import date
from decimal import Decimal
from finagent.models import Fact, Provenance, make_fact_id
from finagent.datasource.facts import (
    latest_per_period,
    single_quarters,
    duration_days,
    align_frame,
    calendar_frame,
)


def prov(filed, acc="a", fp="Q2", fy=2024):
    return Provenance(acc, "10-Q", filed, fp, fy, "us-gaap:Revenues", "u", "x", "0")


def fact(val, start, end, filed, frame=None, fp="Q2", fy=2024):
    return Fact(
        make_fact_id(str(start), str(end), filed, str(val)),
        320193,
        "AAPL",
        "Apple",
        Decimal(val),
        "USD",
        "us-gaap:Revenues",
        date.fromisoformat(start),
        date.fromisoformat(end),
        frame,
        prov(filed, fp=fp, fy=fy),
    )


# --- latest_per_period ---

def test_latest_wins():
    old = fact("100", "2024-01-01", "2024-03-31", "2024-04-01")
    new = fact("110", "2024-01-01", "2024-03-31", "2024-06-01")
    m = latest_per_period([old, new])
    assert m[("us-gaap:Revenues", date(2024, 3, 31))].value == Decimal("110")


# --- duration_days ---

def test_duration_days():
    f = fact("100", "2024-01-01", "2024-03-31", "2024-04-01")
    assert duration_days(f) == 90


# --- calendar_frame ---

def test_calendar_frame_q1_mar():
    assert calendar_frame(date(2024, 3, 30)) == "CY2024Q1"


def test_calendar_frame_q2_jun():
    assert calendar_frame(date(2024, 6, 30)) == "CY2024Q2"


def test_calendar_frame_q3_sep():
    assert calendar_frame(date(2024, 9, 28)) == "CY2024Q3"


def test_calendar_frame_q4_dec():
    assert calendar_frame(date(2024, 12, 28)) == "CY2024Q4"


def test_calendar_frame_jan_belongs_to_prior_q4():
    assert calendar_frame(date(2025, 1, 25)) == "CY2024Q4"


# --- single_quarters ---

def test_ytd_difference():
    q1 = fact("100", "2024-01-01", "2024-03-31", "2024-04-01", "CY2024Q1", fp="Q1", fy=2024)
    h1 = fact("230", "2024-01-01", "2024-06-30", "2024-07-01", "CY2024H1", fp="Q2", fy=2024)
    qs = single_quarters([q1, h1])
    by_end = {f.period_end: f for f in qs}
    # native Q1 preserved
    assert by_end[date(2024, 3, 31)].value == Decimal("100")
    # derived Q2 = H1 - Q1
    assert by_end[date(2024, 6, 30)].value == Decimal("130")  # 230-100
    # derived fact has raw_value marker
    assert by_end[date(2024, 6, 30)].provenance.raw_value == "derived:YTD_DIFF"
    # derived fact frame computed from calendar end
    assert by_end[date(2024, 6, 30)].frame == "CY2024Q2"
    # cumulative H1 fact itself must NOT appear
    ends = [f.period_end for f in qs]
    values_at_jun30 = [f.value for f in qs if f.period_end == date(2024, 6, 30)]
    assert Decimal("230") not in values_at_jun30
    # only 2 facts total: native Q1 + derived Q2
    assert len(qs) == 2


def test_native_single_quarter_kept():
    q1 = fact("100", "2024-01-01", "2024-03-31", "2024-04-01", "CY2024Q1", fp="Q1", fy=2024)
    qs = single_quarters([q1])
    assert len(qs) == 1
    assert qs[0].value == Decimal("100")


def test_annual_excluded():
    annual = fact("500", "2024-01-01", "2024-12-31", "2025-02-01", "CY2024", fp="FY", fy=2024)
    qs = single_quarters([annual])
    assert len(qs) == 0


# --- align_frame ---

def test_align_frame():
    q1 = fact("100", "2024-01-01", "2024-03-31", "2024-04-01", "CY2024Q1", fp="Q1", fy=2024)
    q2 = fact("130", "2024-04-01", "2024-06-30", "2024-07-01", "CY2024Q2", fp="Q2", fy=2024)
    result = align_frame([q1, q2])
    assert "CY2024Q1" in result
    assert "CY2024Q2" in result
    assert len(result["CY2024Q1"]) == 1
    assert len(result["CY2024Q2"]) == 1


def test_align_frame_skips_none():
    f = fact("100", "2024-01-01", "2024-03-31", "2024-04-01", frame=None)
    result = align_frame([f])
    assert len(result) == 0
