from decimal import Decimal
from finagent.models import Claim
from finagent.metrics import scale_value


def build_evidence_bundle(facts, derived):
    """Build an evidence bundle dict and a lookup index from raw Facts and DerivedFacts.

    Display formatting rules:
      - Fact: display = str(scale_value(f.value, "millions"))  (e.g. "119580.00")
      - DerivedFact with formula in ("ratio", "yoy"): display = f"{(d.value*100).quantize(Decimal('0.1'))}%"  (e.g. "5.4%")
      - Other DerivedFact: display = str(d.value)

    The same display string is stored on both the bundle item and the index entry,
    so Gate 1 of the verifier can compare normalized number tokens against it.
    """
    items = []
    index = {}

    for f in facts:
        disp = str(scale_value(f.value, "millions"))
        label = f"{f.ticker} {f.frame or f.period_end} {f.concept}"
        items.append({
            "fact_id": f.fact_id,
            "label": label,
            "display": disp,
            "company": f.ticker,
            "frame": f.frame,
        })
        index[f.fact_id] = type("E", (), {
            "display": disp,
            "company": f.ticker,
            "frame": f.frame,
        })()

    for d in derived:
        if d.formula in ("ratio", "yoy"):
            disp = f"{(d.value * 100).quantize(Decimal('0.1'))}%"
            cell_val = str((d.value * 100).quantize(Decimal("0.000001")))
        else:
            disp = str(d.value)
            cell_val = str(d.value)
        items.append({
            "fact_id": d.fact_id,
            "label": d.formula,
            "display": disp,
        })
        index[d.fact_id] = type("E", (), {"display": disp, "cell_value": cell_val})()

    return {"items": items}, index


SUMMARIZER_SYSTEM = (
    "You write claims strictly from the evidence bundle. Every sentence with a "
    "number is claim_type datapoint and must cite evidence ids whose display "
    "string contains that exact number. Qualitative sentences are interpretation "
    "with empty evidence. No other companies or periods."
)


def parse_claims(data):
    """Parse a list of Claim objects from a structured dict (LLM output)."""
    return [
        Claim(c["id"], c["text"], tuple(c["evidence_ids"]), c["claim_type"])
        for c in data["claims"]
    ]
