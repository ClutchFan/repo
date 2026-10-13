from datetime import date
from decimal import Decimal
from finagent.models import Fact, Provenance, make_fact_id
from finagent.datasource.facts import (
    latest_per_period,
    single_quarters,
    quarter_facts,
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
    key = ("us-gaap:Revenues", date(2024, 1, 1), date(2024, 3, 31))
    assert m[key].value == Decimal("110")


def test_different_starts_same_end_both_retained():
    """Native Q2 (Apr1-Jun30) and H1 cumulative (Jan1-Jun30) share end date
    but have different starts -- both are different facts and must both survive
    the dedup so single_quarters can derive from the cumulative."""
    q2_native = fact("120", "2024-04-01", "2024-06-30", "2024-07-01", fp="Q2", fy=2024)
    h1 = fact("230", "2024-01-01", "2024-06-30", "2024-07-01", fp="Q2", fy=2024)
    m = latest_per_period([q2_native, h1])
    # Both should be present -- different start dates = different facts
    assert len(m) == 2
    assert ("us-gaap:Revenues", date(2024, 4, 1), date(2024, 6, 30)) in m
    assert ("us-gaap:Revenues", date(2024, 1, 1), date(2024, 6, 30)) in m


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


# --- Defect 1: 3-level chain, prefix must include earlier cumulatives ---

def test_three_level_chain_uses_cumulative_prefix():
    """Q1 + H1 + 9M: Q3 must be 9M - H1 (=170), not 9M - Q1 (=300)."""
    q1 = fact("100", "2024-01-01", "2024-03-31", "2024-04-01", "CY2024Q1", fp="Q1", fy=2024)
    h1 = fact("230", "2024-01-01", "2024-06-30", "2024-07-01", "CY2024H1", fp="Q2", fy=2024)
    nine_m = fact("400", "2024-01-01", "2024-09-30", "2024-11-01", "CY2024Q3", fp="Q3", fy=2024)
    qs = single_quarters([q1, h1, nine_m])
    by_end = {f.period_end: f for f in qs}
    assert by_end[date(2024, 3, 31)].value == Decimal("100")   # native Q1
    assert by_end[date(2024, 6, 30)].value == Decimal("130")   # derived Q2 = H1 - Q1
    assert by_end[date(2024, 9, 30)].value == Decimal("170")   # derived Q3 = 9M - H1, NOT 9M - Q1
    assert len(qs) == 3


# --- Defect 2: native quarter wins over derived at same period_end ---

def test_native_quarter_wins_over_derived():
    """Native Q2 (Apr1-Jun30) + H1 cumulative -> one fact at Jun30, the native one."""
    q1 = fact("100", "2024-01-01", "2024-03-31", "2024-04-01", "CY2024Q1", fp="Q1", fy=2024)
    q2_native = fact("120", "2024-04-01", "2024-06-30", "2024-07-01", "CY2024Q2", fp="Q2", fy=2024)
    h1 = fact("230", "2024-01-01", "2024-06-30", "2024-07-01", "CY2024H1", fp="Q2", fy=2024)
    qs = single_quarters([q1, q2_native, h1])
    # Exactly one fact at Jun30, and it's the native reported value
    jun30_facts = [f for f in qs if f.period_end == date(2024, 6, 30)]
    assert len(jun30_facts) == 1
    assert jun30_facts[0].value == Decimal("120")
    # H1 cumulative value 230 must not appear anywhere
    all_values = [f.value for f in qs]
    assert Decimal("230") not in all_values
    assert len(qs) == 2  # native Q1 + native Q2


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


# --- quarter_facts pipeline ---

def test_quarter_facts_pipeline():
    """quarter_facts = single_quarters after latest_per_period dedup.

    Feeds in raw-style facts with a duplicate revision and a cumulative.
    Verifies: revision value wins dedup, cumulative is excluded from output,
    derived quarter is produced from cumulative.
    """
    # Q1: two revisions (old=100, new=105) -- new should win
    q1_old = fact("100", "2024-01-01", "2024-03-31", "2024-04-01", "CY2024Q1", fp="Q1", fy=2024)
    q1_new = fact("105", "2024-01-01", "2024-03-31", "2024-05-01", "CY2024Q1", fp="Q1", fy=2024)
    # H1 cumulative -- should be used for derivation but excluded from output
    h1 = fact("235", "2024-01-01", "2024-06-30", "2024-07-01", "CY2024H1", fp="Q2", fy=2024)

    qs = quarter_facts([q1_old, q1_new, h1])
    by_end = {f.period_end: f for f in qs}
    # Revision dedup: Q1 should be 105 (later filing), not 100
    assert by_end[date(2024, 3, 31)].value == Decimal("105")
    # Derived Q2 = H1 - Q1 = 235 - 105 = 130
    assert by_end[date(2024, 6, 30)].value == Decimal("130")
    # H1 cumulative value 235 must not appear (excluded from output)
    all_values = [f.value for f in qs]
    assert Decimal("235") not in all_values
    assert len(qs) == 2
