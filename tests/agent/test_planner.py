from finagent.agent.planner import validate_plan
from finagent.models import Company, LineItem, PeriodSpec, QueryPlan

AAPL = Company("AAPL", 320193, "Apple Inc.")


def plan(concepts=("us-gaap:Revenues",)):
    return QueryPlan(
        (AAPL,),
        (LineItem("revenue", concepts, "USD", "millions"),),
        PeriodSpec("last_n_quarters", 1),
        ("table",),
    )


def test_unknown_concept_rejected():
    errs = validate_plan(
        plan(("us-gaap:Nope",)),
        {AAPL: {"us-gaap:Revenues"}, "frames": {"CY2024Q1"}},
    )
    assert any("concept" in e for e in errs)


def test_valid_plan():
    errs = validate_plan(
        plan(),
        {AAPL: {"us-gaap:Revenues"}, "frames": {"CY2024Q1"}},
    )
    assert errs == []


def test_unresolved_company():
    MSFT = Company("MSFT", 789019, "Microsoft Corp.")
    p = QueryPlan(
        (MSFT,),
        (LineItem("revenue", ("us-gaap:Revenues",), "USD", "millions"),),
        PeriodSpec("last_n_quarters", 1),
        ("table",),
    )
    errs = validate_plan(p, {AAPL: {"us-gaap:Revenues"}, "frames": {"CY2024Q1"}})
    assert any("unresolved" in e for e in errs)


def test_no_quarterly_frames():
    errs = validate_plan(plan(), {AAPL: {"us-gaap:Revenues"}, "frames": set()})
    assert any("no quarterly frames" in e for e in errs)


def test_concepts_dict_form():
    """validate_plan should accept both a bare set and a {"concepts": set()} value."""
    errs = validate_plan(
        plan(),
        {AAPL: {"concepts": {"us-gaap:Revenues"}}, "frames": {"CY2024Q1"}},
    )
    assert errs == []

    errs = validate_plan(
        plan(("us-gaap:Nope",)),
        {AAPL: {"concepts": {"us-gaap:Revenues"}}, "frames": {"CY2024Q1"}},
    )
    assert any("concept" in e for e in errs)
