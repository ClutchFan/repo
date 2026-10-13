from datetime import date
from decimal import Decimal

from finagent.output.table import build_table
from finagent.models import Company, LineItem, PeriodSpec, QueryPlan, Fact, Provenance, make_fact_id

A = Company("AAPL", 320193, "Apple")


def fact(frame, val, concept="us-gaap:Revenues", fp="Q1", fy=2024):
    return Fact(
        make_fact_id(frame, concept, str(val)),
        320193,
        "AAPL",
        "Apple",
        Decimal(val),
        "USD",
        concept,
        date(2024, 1, 1),
        date(2024, 3, 31),
        frame,
        Provenance("a", "10-Q", "d", fp, fy, concept, "u", "x", str(val)),
    )


def plan(items):
    return QueryPlan((A,), items, PeriodSpec("last_n_quarters", 1), ("table",))


def test_raw_row_and_missing():
    li = LineItem("revenue", ("us-gaap:Revenues",), "USD", "millions")
    t = build_table(plan((li,)), {A: [fact("CY2024Q1", "119580000000")]})
    assert t.columns == ("CY2024Q1",)
    assert t.rows[0].cells[0].value == Decimal("119580.00")
    li2 = LineItem("revenue", ("us-gaap:Revenues",), "USD", "millions")
    t2 = build_table(plan((li2,)), {A: [fact("CY2024Q1", "50000000000", "us-gaap:GrossProfit")]})
    assert t2.rows[0].cells[0].value is None and "N/A" in t2.rows[0].cells[0].note


def test_gross_margin():
    gp = LineItem("gross_profit", ("us-gaap:GrossProfit",), "USD", "millions")
    rv = LineItem("revenue", ("us-gaap:Revenues",), "USD", "millions")
    gm = LineItem(
        "gross_margin",
        ("us-gaap:GrossProfit", "us-gaap:Revenues"),
        "USD",
        "millions",
        kind="derived",
        formula="gross_profit/revenue",
    )
    pl = QueryPlan((A,), (gp, rv, gm), PeriodSpec("last_n_quarters", 1), ("table",))
    data = {
        A: [
            fact("CY2024Q1", "50000000000", "us-gaap:GrossProfit"),
            fact("CY2024Q1", "100000000000", "us-gaap:Revenues"),
        ]
    }
    gmrow = [r for r in build_table(pl, data).rows if r.alias == "gross_margin"][0]
    assert gmrow.cells[0].value == Decimal("50.000000") and gmrow.formula
