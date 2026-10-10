import json
import pathlib
from decimal import Decimal
from finagent.datasource.facts import normalize_company_facts, available_concepts, facts_for_concept

FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "companyfacts_small.json"

def test_normalize():
    facts = normalize_company_facts(json.loads(FIX.read_text()))
    assert len(facts) == 2
    rev = [f for f in facts if f.concept.endswith("Revenues")][0]
    assert rev.value == Decimal("119580000000")
    assert rev.ticker == "AAPL" and rev.cik == 320193 and rev.frame == "CY2024Q1"
    assert rev.provenance.accession == "0000320193-24-000006"
    assert rev.provenance.source_url.startswith("https://www.sec.gov/")
    assert "us-gaap:Revenues" in available_concepts(facts)
    assert len(facts_for_concept(facts, "us-gaap:Revenues")) == 1
