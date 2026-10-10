from finagent.datasource.taxonomy import concepts_for, pick_concept

def test_fallback_order():
    cs = concepts_for("revenue")
    assert cs[0].endswith("RevenueFromContractWithCustomerExcludingAssessedTax")
    assert pick_concept("revenue", {"us-gaap:Revenues"}) == "us-gaap:Revenues"
    assert pick_concept("revenue", {"us-gaap:Other"}) is None
