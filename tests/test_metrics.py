from decimal import Decimal
from finagent.metrics import ratio, yoy, scale_value
from finagent.models import Fact, Provenance, make_fact_id
from datetime import date

def f(v): return Fact(make_fact_id(v),1,"T","T",Decimal(v),"USD","c",
    date(2024,1,1),date(2024,3,31),None,Provenance("a","10-Q","d","Q1",2024,"c","u","x","0"))

def test_ratio():
    d = ratio(f("50"), f("100")); assert d.value == Decimal("0.5") and d.formula == "ratio"
    assert len(d.input_fact_ids) == 2

def test_yoy():
    assert yoy(f("105"), f("100")).value == Decimal("0.05")

def test_scale():
    assert scale_value(Decimal("119580000000"), "millions") == Decimal("119580")
