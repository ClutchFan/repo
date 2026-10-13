import pytest
from decimal import Decimal
from datetime import date
from finagent.models import Fact, Provenance, DerivedFact, make_fact_id

def _prov(**kw):
    base = dict(accession="a", form="10-Q", filed_date="2024-02-02",
                fiscal_period="Q1", fiscal_year=2024, concept="us-gaap:Revenues",
                source_url="u", xbrl_fact_url="x", raw_value="1000")
    base.update(kw); return Provenance(**base)

def test_fact_is_immutable():
    f = Fact(make_fact_id("f"), 1, "X", "X Co", Decimal("1000"), "USD",
             "us-gaap:Revenues", date(2024,1,1), date(2024,3,31), "CY2024Q1", _prov())
    with pytest.raises(Exception):
        f.value = Decimal("2")  # type: ignore

def test_fact_id_deterministic():
    assert make_fact_id("a","b") == make_fact_id("a","b")
    assert make_fact_id("a") != make_fact_id("b")
