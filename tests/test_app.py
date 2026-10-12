"""Tests for finagent.app orchestration and finagent.output.cli rendering."""
import json
import pathlib
from decimal import Decimal
from datetime import date

import pytest

from finagent.app import Result, run_query
from finagent.profile.store import ProfileStore, Profile
from finagent.datasource.tickers import TickerResolver
from finagent.agent.tools import DataTools
from finagent.agent.loop import AgentLoop
from finagent.models import Company, Fact, Provenance, make_fact_id
from finagent.output.cli import render_console


# ---------------------------------------------------------------------------
# FakeSEC — implements get_ticker_index / get_company_facts (same shape as SECClient)
# ---------------------------------------------------------------------------

class FakeSEC:
    def __init__(self, tickers=None, facts_by_cik=None):
        self._tickers = tickers or [
            {"ticker": "AAPL", "cik": 320193, "title": "Apple Inc."},
        ]
        self._facts_by_cik = facts_by_cik or {}

    def get_ticker_index(self):
        return list(self._tickers)

    def get_company_facts(self, cik):
        if cik in self._facts_by_cik:
            return self._facts_by_cik[cik]
        # default AAPL single-quarter revenue
        return _aapl_companyfacts()


def _aapl_companyfacts():
    return {
        "cik": 320193,
        "ticker": "AAPL",
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "val": "119580000000",
                                "start": "2024-01-01",
                                "end": "2024-03-31",
                                "form": "10-Q",
                                "filed": "2024-05-01",
                                "acc": "0000320193-24-000006",
                                "frame": "CY2024Q1",
                                "fy": 2024,
                                "fp": "Q1",
                            },
                        ]
                    }
                },
                "GrossProfit": {
                    "units": {
                        "USD": [
                            {
                                "val": "50000000000",
                                "start": "2024-01-01",
                                "end": "2024-03-31",
                                "form": "10-Q",
                                "filed": "2024-05-01",
                                "acc": "0000320193-24-000006",
                                "frame": "CY2024Q1",
                                "fy": 2024,
                                "fp": "Q1",
                            },
                        ]
                    }
                },
            }
        },
    }


# ---------------------------------------------------------------------------
# ScriptedLLM — returns canned responses in order, works like LLMClient.complete_json
# ---------------------------------------------------------------------------

class ScriptedLLM:
    def __init__(self, outs):
        self.outs = list(outs)
        self.i = 0
        self.calls = []  # record (system, messages, schema) for assertions

    def complete_json(self, system, messages, schema, tools=None):
        self.calls.append((system, messages, schema, tools))
        if self.i >= len(self.outs):
            raise RuntimeError(f"ScriptedLLM ran out of responses (called {self.i + 1} times)")
        o = self.outs[self.i]
        self.i += 1
        return o


# ---------------------------------------------------------------------------
# Shared plan payload used by most tests
# ---------------------------------------------------------------------------

AAPL_PLAN = {
    "final": {
        "companies": [{"ticker": "AAPL", "cik": 320193, "name": "Apple Inc."}],
        "line_items": [
            {
                "alias": "revenue",
                "concepts": ["us-gaap:Revenues"],
                "unit": "USD",
                "scaling": "millions",
            }
        ],
        "periods": {"type": "last_n_quarters", "n": 1},
        "outputs": ["table"],
    }
}


def _good_claims_payload(fact_id):
    """A claims payload whose datapoint number matches the evidence display."""
    return {
        "claims": [
            {
                "id": "c1",
                "text": f"AAPL revenue in CY2024Q1 was 119580.00 million USD.",
                "evidence_ids": [fact_id],
                "claim_type": "datapoint",
            },
            {
                "id": "c2",
                "text": "Apple had a strong quarter.",
                "evidence_ids": [],
                "claim_type": "interpretation",
            },
        ]
    }


def _bad_claims_payload(fact_id):
    """First attempt: hallucinated number that won't match evidence."""
    return {
        "claims": [
            {
                "id": "c1",
                "text": f"AAPL revenue in CY2024Q1 was 999999 million USD.",
                "evidence_ids": [fact_id],
                "claim_type": "datapoint",
            },
        ]
    }


def _find_revenue_fact_id(index):
    """Find the fact_id for the revenue fact from the evidence index."""
    for fid, entry in index.items():
        if "Revenues" in getattr(entry, "label", "") or (
            hasattr(entry, "company") and hasattr(entry, "frame") and "Revenues" not in str(entry)
        ):
            pass
    # simpler: just return the only (or first) fact id
    for fid in index:
        return fid
    return None


# ---------------------------------------------------------------------------
# Test 1: Happy path — one datapoint claim passes, verdict ok, downgraded 0
# ---------------------------------------------------------------------------

def test_run_query_happy_path(tmp_path):
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    # Prime tools cache so we know the fact_id in advance
    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    # Planner: resolve_ticker call, then final plan
    # Summarizer: one call with good claims
    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        _good_claims_payload(rev_fact_id),
        # Judge call (always "supported" — our fake judge lambda below)
    ])

    # Write a temp profile
    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
        preferences={"units": "USD", "scaling": "millions"},
    )
    ProfileStore(profile_path).save(profile)

    profile_store = ProfileStore(profile_path)
    profile_obj = profile_store.load()

    # Use a judge that always returns "supported"
    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    assert isinstance(result, Result)
    # Plan is resolved
    assert len(result.plan.companies) == 1
    assert result.plan.companies[0].ticker == "AAPL"
    # Table has one row
    assert len(result.table.rows) == 1
    assert result.table.rows[0].alias == "revenue"
    assert result.table.rows[0].cells[0].value == Decimal("119580.00")
    # Claims: 2 claims (1 datapoint + 1 interpretation)
    assert len(result.claims) == 2
    datapoint = [c for c in result.claims if c.claim_type == "datapoint"][0]
    assert datapoint.id == "c1"
    # All verdicts ok
    assert len(result.verdicts) == 2
    assert all(v.ok for v in result.verdicts)
    assert result.downgraded == 0
    # facts_by_company maps Company -> raw facts list
    assert isinstance(result.facts_by_company, dict)
    comp_key = list(result.facts_by_company.keys())[0]
    assert comp_key.ticker == "AAPL"
    assert isinstance(result.facts_by_company[comp_key], list)
    # index is a dict
    assert isinstance(result.index, dict)


# ---------------------------------------------------------------------------
# Test 2: Rewrite path — first claims fail, second pass (two summarizer calls)
# ---------------------------------------------------------------------------

def test_run_query_rewrite_path(tmp_path):
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    # Planner: resolve_ticker + final plan
    # Summarizer call 1: bad claims (hallucinated number)
    # Summarizer call 2: good claims (correct number)
    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        _bad_claims_payload(rev_fact_id),
        _good_claims_payload(rev_fact_id),
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    # All claims pass after rewrite
    assert result.downgraded == 0
    assert len(result.claims) == 2
    assert all(v.ok for v in result.verdicts)
    # The bad first attempt should have caused a rewrite (more than 0 summarizer calls)
    # We can verify by checking that more LLM calls happened than just planner + 1 summarizer


# ---------------------------------------------------------------------------
# Test 3: Downgrade path — all attempts fail, datapoint dropped, interpretation retained
# ---------------------------------------------------------------------------

def test_run_query_downgrade_path(tmp_path):
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    # Both attempts return bad claims (hallucinated number never fixed)
    # Plus an interpretation claim that should always be retained
    bad_with_interp = {
        "claims": [
            {
                "id": "c1",
                "text": "AAPL revenue in CY2024Q1 was 999999 million USD.",
                "evidence_ids": [rev_fact_id],
                "claim_type": "datapoint",
            },
            {
                "id": "c2",
                "text": "Apple had a strong quarter.",
                "evidence_ids": [],
                "claim_type": "interpretation",
            },
        ]
    }

    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        bad_with_interp,  # attempt 0: fails
        bad_with_interp,  # attempt 1: fails
        bad_with_interp,  # attempt 2: fails (max_rewrites=2 means 3 total attempts)
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    # Datapoint claim dropped, interpretation retained
    assert len(result.claims) == 1
    assert result.claims[0].claim_type == "interpretation"
    assert result.claims[0].id == "c2"
    # downgraded = number of failed (dropped) claim ids
    assert result.downgraded == 1


# ---------------------------------------------------------------------------
# Test 4: Result field order matches contract
# ---------------------------------------------------------------------------

def test_result_field_order():
    """Result dataclass field order is load-bearing for Task 16/17."""
    import dataclasses
    fields = [f.name for f in dataclasses.fields(Result)]
    assert fields == [
        "plan", "table", "claims", "verdicts",
        "facts_by_company", "index", "downgraded",
    ]


# ---------------------------------------------------------------------------
# Test 5: render_console produces output with table + claims + footer
# ---------------------------------------------------------------------------

def test_render_console_output(tmp_path):
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        _good_claims_payload(rev_fact_id),
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    output = render_console(result)
    assert isinstance(output, str)
    # Table header / content
    assert "AAPL" in output
    assert "revenue" in output
    assert "CY2024Q1" in output
    # Claims with verdict markers
    assert "✓" in output or "ok" in output.lower()
    # Footer format: 【核查】X passed · N downgraded
    assert "【核查】" in output
    assert "passed" in output
    assert "downgraded" in output


# ---------------------------------------------------------------------------
# Test 6: known_provider path — plan validates against actual facts
# ---------------------------------------------------------------------------

def test_known_provider_validates_plan(tmp_path):
    """If the planner returns a plan with an unavailable concept, known_provider
    should catch it and the planner should correct itself."""
    sec = FakeSEC()  # only has Revenues and GrossProfit
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    # Planner: resolve -> bad plan (asks for NetIncome, which doesn't exist)
    # -> plan rejected -> corrected plan (asks for Revenues)
    bad_plan = {
        "final": {
            "companies": [{"ticker": "AAPL", "cik": 320193, "name": "Apple Inc."}],
            "line_items": [
                {
                    "alias": "net_income",
                    "concepts": ["us-gaap:NetIncome"],
                    "unit": "USD",
                    "scaling": "millions",
                }
            ],
            "periods": {"type": "last_n_quarters", "n": 1},
            "outputs": ["table"],
        }
    }

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        bad_plan,   # will be rejected by known_provider validation
        AAPL_PLAN,  # corrected plan
        _good_claims_payload(rev_fact_id),
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    # Should succeed with the corrected plan
    assert result.table.rows[0].alias == "revenue"
    assert result.downgraded == 0


# ---------------------------------------------------------------------------
# Test 7: facts_by_company contains RAW facts (not quarter_facts)
# ---------------------------------------------------------------------------

def test_facts_by_company_are_raw(tmp_path):
    """Cross-task fact 2: facts_by_company maps Company -> raw normalized facts.
    build_table internally applies quarter_facts()."""
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        _good_claims_payload(rev_fact_id),
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    comp_key = list(result.facts_by_company.keys())[0]
    raw = result.facts_by_company[comp_key]
    # Raw facts from normalize_company_facts may have multiple per concept
    # (e.g. different units), but all facts should have the raw structure.
    assert isinstance(raw, list)
    assert len(raw) > 0
    # Raw facts are direct output of normalize_company_facts — no YTD_DIFF provenance
    derived_count = sum(
        1 for f in raw if getattr(f.provenance, "raw_value", "") == "derived:YTD_DIFF"
    )
    assert derived_count == 0, "facts_by_company must be raw, not quarter_facts (no YTD_DIFF)"


# ---------------------------------------------------------------------------
# Test 8: Rewrite path — exactly 2 summarizer LLM calls (first fails, second passes)
# ---------------------------------------------------------------------------

def test_rewrite_makes_two_summarizer_calls(tmp_path):
    """In the rewrite path, the summarizer is called twice."""
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        _bad_claims_payload(rev_fact_id),   # summarizer call 1: fails
        _good_claims_payload(rev_fact_id),  # summarizer call 2: passes
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    assert result.downgraded == 0
    # LLM calls: 1 resolve_ticker + 1 plan + 2 summarizer = 4 total
    assert llm.i == 4, f"Expected 4 LLM calls, got {llm.i}"


# ---------------------------------------------------------------------------
# Test 9: Downgrade footer — "0 passed · 1 downgraded" with interpretation retained
# ---------------------------------------------------------------------------

def test_render_console_downgrade_footer(tmp_path):
    """Footer should show only retained ok claims in the passed count."""
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    bad_with_interp = {
        "claims": [
            {
                "id": "c1",
                "text": "AAPL revenue in CY2024Q1 was 999999 million USD.",
                "evidence_ids": [rev_fact_id],
                "claim_type": "datapoint",
            },
            {
                "id": "c2",
                "text": "Apple had a strong quarter.",
                "evidence_ids": [],
                "claim_type": "interpretation",
            },
        ]
    }

    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        bad_with_interp,
        bad_with_interp,
        bad_with_interp,
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    output = render_console(result)
    # Interpretation claim is retained and auto-ok -> 1 passed
    assert "【核查】1 passed · 1 downgraded" in output
    # Interpretation marker should appear
    assert "【模型解读，非数据】" in output


# ---------------------------------------------------------------------------
# Test 10: Forbidden companies computed from COVERED_TICKERS - scope
# ---------------------------------------------------------------------------

def test_forbidden_companies_from_covered_tickers(tmp_path):
    """Forbidden set = COVERED_TICKERS - scope. A claim mentioning a ticker
    outside scope but inside COVERED_TICKERS should fail company gate."""
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    # Claim mentions MSFT (in COVERED_TICKERS but not in scope {AAPL})
    msft_claim = {
        "claims": [
            {
                "id": "c1",
                "text": "MSFT revenue was also 119580.00 million.",
                "evidence_ids": [rev_fact_id],
                "claim_type": "datapoint",
            },
        ]
    }

    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        msft_claim,
        msft_claim,
        msft_claim,
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=2,
    )

    # MSFT is in COVERED_TICKERS but not in scope {AAPL} -> forbidden -> claim fails
    assert result.downgraded == 1
    assert len(result.claims) == 0


# ---------------------------------------------------------------------------
# Test 11: max_rewrites=0 means exactly one attempt (no retries)
# ---------------------------------------------------------------------------

def test_max_rewrites_zero(tmp_path):
    sec = FakeSEC()
    resolver = TickerResolver(sec)
    tools = DataTools(sec, resolver)

    raw_facts = tools._facts_for(320193)
    from finagent.datasource.facts import quarter_facts
    qf = quarter_facts(raw_facts)
    rev_fact = [f for f in qf if "Revenues" in f.concept][0]
    rev_fact_id = rev_fact.fact_id

    llm = ScriptedLLM([
        {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
        AAPL_PLAN,
        _bad_claims_payload(rev_fact_id),
    ])

    profile_path = tmp_path / "profile.json"
    profile = Profile(
        watchlist=[Company("AAPL", 320193, "Apple Inc.")],
        metric_aliases={},
        default_quarters=4,
    )
    ProfileStore(profile_path).save(profile)
    profile_obj = ProfileStore(profile_path).load()

    def fake_judge(claim):
        return "supported"

    result = run_query(
        question="What was AAPL revenue?",
        llm=llm,
        sec=sec,
        resolver=resolver,
        profile=profile_obj,
        judge=fake_judge,
        max_rewrites=0,  # no retries
    )

    assert result.downgraded == 1
    # LLM calls: 1 resolve + 1 plan + 1 summarizer = 3
    assert llm.i == 3


# ---------------------------------------------------------------------------
# Test 12: COVERED_TICKERS constant includes AAPL (cross-task fact 3)
# ---------------------------------------------------------------------------

def test_covered_tickers_includes_aapl():
    from finagent.app import COVERED_TICKERS
    assert "AAPL" in COVERED_TICKERS
    assert "MSFT" in COVERED_TICKERS
    assert "NVDA" in COVERED_TICKERS
    assert "GOOG" in COVERED_TICKERS
    assert len(COVERED_TICKERS) == 4
