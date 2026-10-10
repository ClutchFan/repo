from decimal import Decimal, ROUND_HALF_UP
from finagent.models import DerivedFact, make_fact_id
_S = {"raw": 1, "thousands": 1e3, "millions": 1e6, "billions": 1e9}
SCALINGS = tuple(_S)

def _d(x):
    return Decimal(str(x))

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
    return (value / _d(_S[scaling])).quantize(Decimal("0.01"), ROUND_HALF_UP)
