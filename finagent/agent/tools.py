from dataclasses import asdict
from finagent.datasource.tickers import AmbiguousTicker
from finagent.datasource.facts import (
    normalize_company_facts,
    available_concepts,
    facts_for_concept,
    quarter_facts,
)


class DataTools:
    def __init__(self, sec, resolver):
        self.sec = sec
        self.resolver = resolver
        self._facts = {}

    def _facts_for(self, cik):
        if cik not in self._facts:
            self._facts[cik] = normalize_company_facts(self.sec.get_company_facts(cik))
        return self._facts[cik]

    def resolve_ticker(self, ticker):
        try:
            c = self.resolver.resolve(ticker)
            return {"ok": True, "company": asdict(c)}
        except AmbiguousTicker as e:
            return {"ok": False, "candidates": [asdict(x) for x in e.candidates]}

    def list_concepts(self, cik, query):
        q = query.lower()
        cs = sorted(
            c for c in available_concepts(self._facts_for(cik)) if q in c.lower()
        )
        return {"concepts": cs}

    def list_available_periods(self, cik):
        fs = quarter_facts(self._facts_for(cik))
        return {"frames": sorted({f.frame for f in fs if f.frame})}

    def preview_metric(self, cik, concept):
        fs = facts_for_concept(self._facts_for(cik), concept)
        if not fs:
            return {"ok": False, "reason": "not reported"}
        f = sorted(fs, key=lambda x: x.period_end)[-1]
        return {
            "ok": True,
            "value": str(f.value),
            "unit": f.unit,
            "frame": f.frame,
            "accession": f.provenance.accession,
        }

    def call(self, name, args):
        fn = getattr(self, name, None)
        if fn is None:
            return {"ok": False, "error": f"unknown tool {name}"}
        try:
            return fn(**args)
        except TypeError as e:
            return {"ok": False, "error": str(e)}
