import dataclasses
from datetime import date
from decimal import Decimal
from finagent.models import Fact, Provenance, make_fact_id

def fact_urls(cik, accession):
    nodash = accession.replace("-", "")
    browse = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nodash}/{accession}-index.htm"
    viewer = f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={int(cik)}&accession_number={accession}"
    return browse, viewer

def _d(s): return date.fromisoformat(s) if s else None

def normalize_company_facts(payload):
    cik = int(payload["cik"]); ticker = payload.get("ticker") or ""
    name = payload.get("entityName", "")
    out = []
    for taxonomy, concepts in payload.get("facts", {}).items():
        for concept, body in concepts.items():
            full = f"{taxonomy}:{concept}"
            for unit, entries in body.get("units", {}).items():
                for e in entries:
                    if not all(k in e for k in ("acc", "filed", "form", "end")): continue
                    start = _d(e.get("start")); end = _d(e["end"])
                    src, viewer = fact_urls(cik, e["acc"])
                    prov = Provenance(e["acc"], e["form"], e["filed"],
                        e.get("fp",""), int(e.get("fy",0)), full, src, viewer, str(e["val"]))
                    fid = make_fact_id(ticker, full, unit, str(start), str(end), e["acc"], str(e["val"]))
                    out.append(Fact(fid, cik, ticker, name, Decimal(str(e["val"])), unit,
                        full, start or end, end, e.get("frame"), prov))
    return out

def available_concepts(facts): return {f.concept for f in facts}
def facts_for_concept(facts, concept): return [f for f in facts if f.concept == concept]


def calendar_frame(end) -> str:
    """Map a quarter-end date to an SEC-style calendar frame 'CYYYYQn'.

    Months 2,3,4 -> Q1; 5,6,7 -> Q2; 8,9,10 -> Q3; 11,12,1 -> Q4.
    A quarter ending in January belongs to the prior calendar year's Q4.
    """
    m = end.month
    if m in (2, 3, 4):
        q = 1
        y = end.year
    elif m in (5, 6, 7):
        q = 2
        y = end.year
    elif m in (8, 9, 10):
        q = 3
        y = end.year
    else:  # 11, 12, 1
        q = 4
        y = end.year if m != 1 else end.year - 1
    return f"CY{y}Q{q}"


def duration_days(f: Fact) -> int:
    return (f.period_end - f.period_start).days


def latest_per_period(facts: list[Fact]) -> dict[tuple[str, date], Fact]:
    """Dedupe by (concept, period_end), keeping the fact with greatest filed_date."""
    out = {}
    for f in facts:
        key = (f.concept, f.period_end)
        cur = out.get(key)
        if cur is None or f.provenance.filed_date > cur.provenance.filed_date:
            out[key] = f
    return out


def single_quarters(facts: list[Fact]) -> list[Fact]:
    """Return ONLY single-quarter facts (one per (concept, period_end)).

    1. Native single-quarter facts (duration <= 120 days) are kept.
    2. For each multi-quarter fact (duration > 120 days), find its longest
       prefix fact (same period_start, earlier period_end, same concept &
       fiscal year). Derive a quarter fact = multi - prefix.
    3. Cumulative / annual source facts are excluded from output.
    """
    # Group by (concept, fiscal_year)
    by_concept_year: dict[tuple[str, int], list[Fact]] = {}
    for f in facts:
        if f.provenance.fiscal_year:
            by_concept_year.setdefault(
                (f.concept, f.provenance.fiscal_year), []
            ).append(f)

    result: list[Fact] = []

    for (concept, fy), group in by_concept_year.items():
        # Native single-quarter facts go directly into the result
        native = [g for g in group if duration_days(g) <= 120]
        result.extend(native)

        # Multi-quarter / cumulative facts: derive single quarters, do NOT include originals
        multis = sorted(
            [g for g in group if duration_days(g) > 120],
            key=lambda g: duration_days(g),
        )

        # Build working set of facts with known period_start that can act as prefixes.
        # Start with native quarters, add derived facts as we go.
        prefixes: list[Fact] = list(native)

        for multi in multis:
            # Find the longest prefix: same period_start, strictly earlier period_end
            best_prefix = None
            for g in prefixes:
                if (
                    g.period_start == multi.period_start
                    and g.period_end < multi.period_end
                ):
                    if best_prefix is None or g.period_end > best_prefix.period_end:
                        best_prefix = g
            if best_prefix is None:
                continue

            derived_value = multi.value - best_prefix.value
            derived_start = date.fromordinal(best_prefix.period_end.toordinal() + 1)
            fid = make_fact_id("YTDDIFF", multi.fact_id, best_prefix.fact_id)
            newprov = dataclasses.replace(multi.provenance, raw_value="derived:YTD_DIFF")
            derived = Fact(
                fid,
                multi.cik,
                multi.ticker,
                multi.company_name,
                derived_value,
                multi.unit,
                multi.concept,
                derived_start,
                multi.period_end,
                calendar_frame(multi.period_end),
                newprov,
            )
            result.append(derived)
            prefixes.append(derived)

    return result


def align_frame(facts: list[Fact]) -> dict[str, list[Fact]]:
    """Group facts by their frame string; facts with no frame are skipped."""
    out: dict[str, list[Fact]] = {}
    for f in facts:
        if f.frame:
            out.setdefault(f.frame, []).append(f)
    return out
