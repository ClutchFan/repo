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
