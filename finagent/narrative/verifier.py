import re
from dataclasses import dataclass

NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
TICKER = re.compile(r"\b[A-Z]{2,5}\b")
INTERP_MARKER = "【模型解读，非数据】"


@dataclass(frozen=True)
class Verdict:
    claim_id: str
    ok: bool
    reason: str


def _norm(t):
    """Normalize a number token: strip commas, remove leading zeros.

    Percent-suffixed tokens keep their '%' so that "5.4%" matches "5.4%" exactly.
    """
    is_pct = t.endswith("%")
    core = t[:-1] if is_pct else t
    core = core.replace(",", "").lstrip("0") or "0"
    return core + ("%" if is_pct else "")


def render_claim_text(c):
    """Render a claim's text with the interpretation marker prefix if applicable."""
    if c.claim_type == "interpretation":
        return f"{INTERP_MARKER} {c.text}"
    return c.text


def verify_claims(claims, index, judge, allowed_companies, forbidden_companies, allowed_frames):
    """Verify a list of Claims against three gates:

    Gate order:
      1. interpretation claims -> auto-ok
      2. datapoint without evidence -> reject
      3. missing evidence id -> reject
      4. bare-number gate: every number token must match (normalized) one of the
         bound evidence display strings
      5. scope gate: any forbidden company token, or a ticker present but none
         in allowed set -> reject
      6. judge(c) must return "supported"

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

        # Gate 3: missing evidence ids (and collect allowed display strings)
        allowed = set()
        missing = False
        for eid in c.evidence_ids:
            e = index.get(eid)
            if e is None:
                out.append(Verdict(c.id, False, f"missing evidence {eid}"))
                missing = True
                break
            allowed.add(_norm(e.display))
        if missing:
            continue

        # Gate 4: bare-number gate
        bad = [n for n in NUM.findall(c.text) if _norm(n) not in allowed]
        if bad:
            out.append(Verdict(c.id, False, f"unsupported numbers {bad}"))
            continue

        # Gate 5: scope gate (company tickers)
        tokens = set(TICKER.findall(c.text))
        if tokens & forbidden_companies or (tokens and not (tokens & allowed_companies)):
            out.append(Verdict(c.id, False, "out-of-scope company"))
            continue

        # Gate 6: judge
        verdict = judge(c)
        if verdict != "supported":
            out.append(Verdict(c.id, False, f"judge:{verdict}"))
            continue

        out.append(Verdict(c.id, True, "ok"))

    return out
