import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass

# Number token regex: supports leading-dot decimals like .5, .5%, and normal numbers
NUM = re.compile(r"-?(?:\d[\d,]*(?:\.\d+)?|\.\d+)%?")
# Frame token regex: CY followed by 4 digits, Q, and 1-4
FRAME = re.compile(r"CY\d{4}Q[1-4]")
INTERP_MARKER = "【模型解读，非数据】"


@dataclass(frozen=True)
class Verdict:
    claim_id: str
    ok: bool
    reason: str


def _parse_number(token):
    """Parse a number token into (Decimal, is_percent).

    Strips thousands commas, detects trailing % flag, parses numeric part with Decimal.
    Returns None if the token cannot be parsed as a valid number.
    """
    is_pct = token.endswith("%")
    core = token[:-1] if is_pct else token
    core = core.replace(",", "")
    try:
        val = Decimal(core)
    except InvalidOperation:
        return None
    return val, is_pct


def _allowed_numbers(evidence_displays):
    """Build a set of (Decimal, is_percent) tuples from evidence display strings.

    Only display strings that parse as valid numbers are included.
    """
    result = set()
    for d in evidence_displays:
        parsed = _parse_number(d)
        if parsed is not None:
            result.add(parsed)
    return result


def _find_number_tokens(text):
    """Extract number tokens from text, excluding those inside frame tokens (CY2024Q1).

    We first remove all frame tokens from the text, then find number tokens in the remainder.
    This prevents digits inside CY2024Q1 from being treated as standalone numeric claims.
    """
    cleaned = FRAME.sub(" ", text)
    return NUM.findall(cleaned)


def render_claim_text(c):
    """Render a claim's text with the interpretation marker prefix if applicable."""
    if c.claim_type == "interpretation":
        return f"{INTERP_MARKER} {c.text}"
    return c.text


def verify_claims(claims, index, judge, allowed_companies, forbidden_companies, allowed_frames):
    """Verify a list of Claims against gates in order:

    1. interpretation claims -> auto-ok
    2. datapoint without evidence -> reject
    3. missing evidence id -> reject
    4. number gate: every number token must match (Decimal equality, same % flag)
       one of the bound evidence display strings
    5. company gate: any forbidden company token (exact member match) -> reject
    6. frame gate: if allowed_frames non-empty, any frame token not in set -> reject
    7. judge(c) must return "supported"

    Returns a list of Verdict objects in the same order as the input claims.
    """
    out = []
    for c in claims:
        # Gate 1: interpretation auto-ok
        if c.claim_type == "interpretation":
            out.append(Verdict(c.id, True, "interpretation"))
            continue

        # Gate 2: datapoint without evidence
        if not c.evidence_ids:
            out.append(Verdict(c.id, False, "datapoint without evidence"))
            continue

        # Gate 3: missing evidence ids (and collect allowed display values)
        allowed_values = set()
        missing = False
        for eid in c.evidence_ids:
            e = index.get(eid)
            if e is None:
                out.append(Verdict(c.id, False, f"missing evidence {eid}"))
                missing = True
                break
            parsed = _parse_number(e.display)
            if parsed is not None:
                allowed_values.add(parsed)
        if missing:
            continue

        # Gate 4: number gate (sound Decimal equality)
        bad = []
        for token in _find_number_tokens(c.text):
            parsed = _parse_number(token)
            if parsed is None:
                bad.append(token)
                continue
            if parsed not in allowed_values:
                bad.append(token)
        if bad:
            out.append(Verdict(c.id, False, f"unsupported numbers {bad}"))
            continue

        # Gate 5: company gate (exact forbidden-members only)
        has_forbidden = False
        for tk in forbidden_companies:
            if re.search(r"\b" + re.escape(tk) + r"\b", c.text):
                has_forbidden = True
                break
        if has_forbidden:
            out.append(Verdict(c.id, False, "out-of-scope company"))
            continue

        # Gate 6: frame gate
        if allowed_frames:
            frame_tokens = FRAME.findall(c.text)
            bad_frames = [f for f in frame_tokens if f not in allowed_frames]
            if bad_frames:
                out.append(Verdict(c.id, False, f"out-of-scope frame {bad_frames}"))
                continue

        # Gate 7: judge
        verdict = judge(c)
        if verdict != "supported":
            out.append(Verdict(c.id, False, f"judge:{verdict}"))
            continue

        out.append(Verdict(c.id, True, "ok"))

    return out
