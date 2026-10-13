from decimal import Decimal, ROUND_HALF_UP
from finagent.models import DerivedFact, make_fact_id
from finagent.datasource.facts import quarter_facts
from finagent.datasource.taxonomy import pick_concept

_S = {"raw": Decimal("1"), "thousands": Decimal("1000"), "millions": Decimal("1000000"), "billions": Decimal("1000000000")}
SCALINGS = tuple(_S)


def ratio(a, b):
    return DerivedFact(make_fact_id("ratio", a.fact_id, b.fact_id),
        (a.value / b.value).quantize(Decimal("0.000001"), ROUND_HALF_UP),
        "ratio",
        (a.fact_id, b.fact_id))


def yoy(cur, prev):
    return DerivedFact(make_fact_id("yoy", cur.fact_id, prev.fact_id),
        ((cur.value - prev.value) / prev.value).quantize(Decimal("0.000001"), ROUND_HALF_UP),
        "yoy", (cur.fact_id, prev.fact_id))


def scale_value(value, scaling):
    return (value / _S[scaling]).quantize(Decimal("0.01"), ROUND_HALF_UP)


def reconstruct_ratio_derived_facts(raw_facts, table_rows, company_ticker):
    """Reconstruct ratio DerivedFact objects for all gross_profit/revenue table rows.

    Shared helper used by both the evidence bundle (app.py) and the XLSX
    provenance sheet (xlsx.py) to ensure consistent derived-fact IDs and values.

    Args:
        raw_facts: list of raw Fact objects for a company (output of normalize_company_facts)
        table_rows: iterable of TableRow objects (from a Table)
        company_ticker: ticker string to match against table rows

    Returns:
        list of DerivedFact objects, one per non-N/A cell in ratio formula rows
        for the given company.
    """
    derived = []
    all_qf = quarter_facts(raw_facts)
    concepts = {f.concept for f in raw_facts}
    qf_map = {(f.concept, f.frame): f for f in all_qf if f.frame}

    gpc = pick_concept("gross_profit", concepts)
    rvc = pick_concept("revenue", concepts)
    if gpc is None or rvc is None:
        return derived

    for row in table_rows:
        if row.formula != "gross_profit/revenue":
            continue
        if row.company != company_ticker:
            continue
        for cell in row.cells:
            if cell.fact_id is None:
                continue
            gp = qf_map.get((gpc, cell.frame))
            rv = qf_map.get((rvc, cell.frame))
            if gp is None or rv is None:
                continue
            d = ratio(gp, rv)
            derived.append(d)

    return derived
