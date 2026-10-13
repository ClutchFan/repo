from decimal import Decimal
from finagent.narrative.verifier import verify_claims, render_claim_text, Verdict
from finagent.narrative.summarizer import build_evidence_bundle, parse_claims, SUMMARIZER_SYSTEM
from finagent.models import Claim, Fact, DerivedFact, Provenance
from datetime import date


def _make_fact(fact_id, ticker, value, unit, concept, frame):
    return Fact(
        fact_id=fact_id,
        cik=123,
        ticker=ticker,
        company_name="Apple Inc.",
        value=Decimal(str(value)),
        unit=unit,
        concept=concept,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        frame=frame,
        provenance=Provenance(
            accession="accession", form="10-Q", filed_date="2024-05-01",
            fiscal_period="Q1", fiscal_year=2024, concept=concept,
            source_url="http://example.com", xbrl_fact_url="http://example.com/xbrl",
            raw_value=str(value),
        ),
    )


def _make_derived(fact_id, value, formula, input_fact_ids):
    return DerivedFact(
        fact_id=fact_id,
        value=Decimal(str(value)),
        formula=formula,
        input_fact_ids=tuple(input_fact_ids),
    )


# ---- Brief Step 1 tests ----

def judge_supported(c):
    return "supported"


idx = {"f1": type("E", (), {"display": "5.4%", "company": "AAPL", "frame": "CY2024Q1"})()}
ARGS = dict(index=idx, judge=judge_supported,
            forbidden_companies={"MSFT", "GOOG", "NVDA"}, allowed_frames={"CY2024Q1"})


def test_bare_number_rejected():
    v = verify_claims([Claim("c1", "Revenue grew 5.4% to 999.", ("f1",), "datapoint")], **ARGS)
    assert v[0].ok is False and "999" in v[0].reason


def test_good_claim_passes():
    v = verify_claims([Claim("c1", "AAPL revenue grew 5.4%.", ("f1",), "datapoint")], **ARGS)
    assert v[0].ok


def test_interpretation_marker():
    assert "模型解读" in render_claim_text(Claim("c", "Solid.", (), "interpretation"))


def test_scope_violation():
    v = verify_claims([Claim("c", "MSFT grew 5.4%.", ("f1",), "datapoint")], **ARGS)
    assert v[0].ok is False


# ---- Additional: raw Fact display test ----

def test_raw_fact_display_and_gate1():
    """A raw Fact with value 119580000000 USD should display as '119580.00' (millions-scaled),
    and a claim containing that number passes Gate 1 while '999' does not."""
    f = _make_fact("f_rev", "AAPL", 119580000000, "USD", "Revenue", "CY2024Q1")
    bundle, index = build_evidence_bundle([f], [])
    # display must normalize to "119580.00"
    entry = index["f_rev"]
    assert entry.display == "119580.00", f"got {entry.display!r}"

    good = Claim("c_good", "AAPL revenue was 119580.00.", ("f_rev",), "datapoint")
    bad = Claim("c_bad", "AAPL revenue was 999.", ("f_rev",), "datapoint")

    local_args = dict(
        index=index, judge=judge_supported,
        forbidden_companies=set(),
        allowed_frames={"CY2024Q1"},
    )
    results = verify_claims([good, bad], **local_args)
    assert results[0].ok is True, f"good claim failed: {results[0].reason}"
    assert results[1].ok is False, "bad claim should fail"
    assert "999" in results[1].reason


# ---- DerivedFact ratio/yoy display test ----

def test_derived_ratio_display():
    d = _make_derived("d_gm", "0.432100", "ratio", ("f1", "f2"))
    bundle, index = build_evidence_bundle([], [d])
    assert index["d_gm"].display == "43.2%"


def test_derived_yoy_display():
    d = _make_derived("d_yoy", "0.054000", "yoy", ("f1", "f2"))
    bundle, index = build_evidence_bundle([], [d])
    assert index["d_yoy"].display == "5.4%"


# ---- parse_claims test ----

def test_parse_claims():
    data = {"claims": [
        {"id": "c1", "text": "Revenue grew.", "evidence_ids": ["f1"], "claim_type": "datapoint"},
        {"id": "c2", "text": "Strong quarter.", "evidence_ids": [], "claim_type": "interpretation"},
    ]}
    claims = parse_claims(data)
    assert len(claims) == 2
    assert isinstance(claims[0], Claim)
    assert claims[0].id == "c1"
    assert claims[0].evidence_ids == ("f1",)
    assert claims[1].claim_type == "interpretation"


# ---- Gate ordering / edge cases ----

def test_interpretation_auto_ok():
    c = Claim("c_int", "Solid management.", (), "interpretation")
    results = verify_claims([c], **ARGS)
    assert results[0].ok is True
    assert results[0].reason == "interpretation"


def test_datapoint_no_evidence_rejected():
    c = Claim("c", "Revenue is up.", (), "datapoint")
    results = verify_claims([c], **ARGS)
    assert results[0].ok is False
    assert "without evidence" in results[0].reason


def test_missing_evidence_id_rejected():
    c = Claim("c", "Revenue grew 5.4%.", ("f_missing",), "datapoint")
    results = verify_claims([c], **ARGS)
    assert results[0].ok is False
    assert "missing" in results[0].reason


def test_judge_contradicted():
    def judge_contradicted(c):
        return "contradicted"
    local_args = dict(ARGS)
    local_args["judge"] = judge_contradicted
    c = Claim("c1", "AAPL revenue grew 5.4%.", ("f1",), "datapoint")
    results = verify_claims([c], **local_args)
    assert results[0].ok is False
    assert "judge:contradicted" in results[0].reason


def test_scope_only_forbidden_members_trigger_company_gate():
    # TSLA is not in forbidden_companies -> company gate passes (no false positive)
    c = Claim("c", "TSLA grew 5.4%.", ("f1",), "datapoint")
    results = verify_claims([c], **ARGS)
    # Not rejected by company gate; judge says supported, so ok
    assert results[0].ok is True


def test_verdict_frozen():
    v = Verdict("c1", True, "ok")
    try:
        v.ok = False
        raise AssertionError("Verdict should be frozen")
    except (AttributeError, TypeError):
        pass


def test_build_evidence_bundle_structure():
    f = _make_fact("f_rev", "AAPL", 119580000000, "USD", "Revenue", "CY2024Q1")
    d = _make_derived("d_gm", "0.432100", "ratio", ("f_rev", "f_cogs"))
    bundle, index = build_evidence_bundle([f], [d])
    assert "items" in bundle
    assert len(bundle["items"]) == 2
    assert index["f_rev"].company == "AAPL"
    assert index["f_rev"].frame == "CY2024Q1"
    assert hasattr(index["d_gm"], "display")


def test_render_claim_text_interpretation_prefix():
    c = Claim("c", "Strong quarter.", (), "interpretation")
    text = render_claim_text(c)
    assert text.startswith("【模型解读，非数据】 ")
    assert "Strong quarter." in text


def test_render_claim_text_datapoint_unchanged():
    c = Claim("c", "Revenue was 100.", ("f1",), "datapoint")
    assert render_claim_text(c) == "Revenue was 100."


def test_number_normalization_commas():
    """Numbers with commas should still match (commas stripped)."""
    f = _make_fact("f_rev", "AAPL", 119580000000, "USD", "Revenue", "CY2024Q1")
    bundle, index = build_evidence_bundle([f], [])
    # Claim uses "119,580.00" with commas -> should match display "119580.00" after normalization
    c = Claim("c", "Revenue was 119,580.00.", ("f_rev",), "datapoint")
    local_args = dict(
        index=index, judge=judge_supported,
        forbidden_companies=set(),
        allowed_frames={"CY2024Q1"},
    )
    results = verify_claims([c], **local_args)
    assert results[0].ok is True, f"comma-formatted number should match: {results[0].reason}"


# ---- FIX 1: Sound numeric equality ----

def test_numeric_equality_leading_dot_decimal():
    """Evidence '0.5%' should match '.5%' via Decimal equality, not string norm."""
    local_idx = {"f1": type("E", (), {"display": "0.5%", "company": "AAPL", "frame": "CY2024Q1"})()}
    local_args = dict(
        index=local_idx, judge=judge_supported,
        forbidden_companies=set(),
        allowed_frames={"CY2024Q1"},
    )
    c = Claim("c", "AAPL grew .5%.", ("f1",), "datapoint")
    results = verify_claims([c], **local_args)
    assert results[0].ok is True, f"leading-dot decimal should match: {results[0].reason}"


def test_numeric_equality_dot_five_not_five():
    """.5 must NOT match integer evidence '5' via Decimal equality."""
    local_idx = {"f1": type("E", (), {"display": "5", "company": "AAPL", "frame": "CY2024Q1"})()}
    local_args = dict(
        index=local_idx, judge=judge_supported,
        forbidden_companies=set(),
        allowed_frames={"CY2024Q1"},
    )
    c = Claim("c", "AAPL had .5 widgets.", ("f1",), "datapoint")
    results = verify_claims([c], **local_args)
    assert results[0].ok is False, ".5 should not match evidence 5"
    assert ".5" in results[0].reason


def test_numeric_equality_trailing_zeros():
    """Evidence '5.4%' should accept '5.40%' (same numeric value)."""
    local_idx = {"f1": type("E", (), {"display": "5.4%", "company": "AAPL", "frame": "CY2024Q1"})()}
    local_args = dict(
        index=local_idx, judge=judge_supported,
        forbidden_companies=set(),
        allowed_frames={"CY2024Q1"},
    )
    c = Claim("c", "AAPL revenue grew 5.40%.", ("f1",), "datapoint")
    results = verify_claims([c], **local_args)
    assert results[0].ok is True, f"trailing-zeros should match: {results[0].reason}"


def test_numeric_equality_integer_form():
    """Evidence '119580.00' should accept '119580' (integer form, same value)."""
    f = _make_fact("f_rev", "AAPL", 119580000000, "USD", "Revenue", "CY2024Q1")
    bundle, index = build_evidence_bundle([f], [])
    c = Claim("c", "AAPL revenue was 119580.", ("f_rev",), "datapoint")
    local_args = dict(
        index=index, judge=judge_supported,
        forbidden_companies=set(),
        allowed_frames={"CY2024Q1"},
    )
    results = verify_claims([c], **local_args)
    assert results[0].ok is True, f"integer form should match decimal display: {results[0].reason}"


def test_numeric_equality_percent_flag_must_match():
    """A plain number must NOT match a percent evidence (different flags)."""
    local_idx = {"f1": type("E", (), {"display": "5.4%", "company": "AAPL", "frame": "CY2024Q1"})()}
    local_args = dict(
        index=local_idx, judge=judge_supported,
        forbidden_companies=set(),
        allowed_frames={"CY2024Q1"},
    )
    c = Claim("c", "AAPL had 5.4 widgets.", ("f1",), "datapoint")
    results = verify_claims([c], **local_args)
    assert results[0].ok is False, "plain 5.4 must not match 5.4%"
    assert "5.4" in results[0].reason


# ---- FIX 2: Company scope only rejects exact forbidden members ----

def test_company_gate_passes_ordinary_acronyms():
    """Ordinary financial acronyms (EPS, GAAP, USD, CEO) must not trigger company gate.
    'AAPL EPS and GAAP revenue grew 5.4%' with allowed {AAPL} must pass."""
    c = Claim("c", "AAPL EPS and GAAP revenue grew 5.4%.", ("f1",), "datapoint")
    results = verify_claims([c], **ARGS)
    assert results[0].ok is True, f"acronyms should not trigger company gate: {results[0].reason}"


def test_company_gate_rejects_forbidden_member_msft():
    """MSFT in forbidden set -> rejected by company gate."""
    c = Claim("c", "MSFT revenue grew 5.4%.", ("f1",), "datapoint")
    results = verify_claims([c], **ARGS)
    assert results[0].ok is False
    assert "company" in results[0].reason


# ---- FIX 3: Frame scope enforcement ----

def test_frame_gate_in_scope_passes():
    """CY2024Q1 is in allowed_frames -> passes frame gate."""
    c = Claim("c", "AAPL revenue in CY2024Q1 grew 5.4%.", ("f1",), "datapoint")
    results = verify_claims([c], **ARGS)
    assert results[0].ok is True, f"in-scope frame should pass: {results[0].reason}"


def test_frame_gate_out_of_scope_rejected():
    """CY2019Q1 not in allowed_frames {CY2024Q1} -> rejected by frame gate."""
    c = Claim("c", "AAPL revenue in CY2019Q1 grew 5.4%.", ("f1",), "datapoint")
    results = verify_claims([c], **ARGS)
    assert results[0].ok is False
    assert "frame" in results[0].reason


def test_frame_gate_empty_allowed_skips_check():
    """If allowed_frames is empty set, frame check is skipped."""
    local_args = dict(ARGS)
    local_args["allowed_frames"] = set()
    c = Claim("c", "AAPL revenue in CY2019Q1 grew 5.4%.", ("f1",), "datapoint")
    results = verify_claims([c], **local_args)
    assert results[0].ok is True, "empty allowed_frames should skip frame check"
