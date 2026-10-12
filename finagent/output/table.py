from dataclasses import dataclass
from decimal import Decimal

from finagent.datasource.taxonomy import pick_concept
from finagent.datasource.facts import quarter_facts
from finagent.metrics import scale_value, ratio


@dataclass(frozen=True)
class Cell:
    frame: str
    value: Decimal | None
    fact_id: str | None
    note: str = ""


@dataclass(frozen=True)
class TableRow:
    company: str
    alias: str
    scaling: str
    cells: tuple[Cell, ...]
    formula: str | None = None


@dataclass(frozen=True)
class Table:
    columns: tuple[str, ...]
    rows: tuple[TableRow, ...]


def _frames(facts_by_company, n):
    fr = set()
    for fs in facts_by_company.values():
        fr |= {f.frame for f in quarter_facts(fs) if f.frame and f.frame.startswith("CY")}
    return tuple(sorted(fr)[-n:])


def _fact_map(facts):
    return {(f.concept, f.frame): f for f in quarter_facts(facts)}


def build_table(plan, facts_by_company):
    cols = _frames(facts_by_company, plan.periods.n)
    rows = []
    for comp in plan.companies:
        facts = facts_by_company.get(comp, [])
        concepts = {f.concept for f in facts}
        sq = _fact_map(facts)
        for li in plan.line_items:
            cells = []
            if li.kind == "derived" and li.formula == "gross_profit/revenue":
                gpc = pick_concept("gross_profit", concepts)
                rvc = pick_concept("revenue", concepts)
                for frame in cols:
                    gp = sq.get((gpc, frame)) if gpc else None
                    rv = sq.get((rvc, frame)) if rvc else None
                    if gp is None or rv is None:
                        cells.append(Cell(frame, None, None, "N/A: inputs not reported"))
                    else:
                        d = ratio(gp, rv)
                        cells.append(Cell(
                            frame,
                            (d.value * 100).quantize(Decimal("0.000001")),
                            d.fact_id,
                            "derived:gross_profit/revenue",
                        ))
                rows.append(TableRow(comp.ticker, li.alias, li.scaling, tuple(cells), li.formula))
                continue
            concept = pick_concept(li.alias, concepts)
            for frame in cols:
                f = sq.get((concept, frame)) if concept else None
                if f is None:
                    cells.append(Cell(frame, None, None, "N/A: not reported"))
                else:
                    note = "derived:YTD_DIFF" if f.provenance.raw_value == "derived:YTD_DIFF" else ""
                    cells.append(Cell(frame, scale_value(f.value, li.scaling), f.fact_id, note))
            rows.append(TableRow(comp.ticker, li.alias, li.scaling, tuple(cells)))
    return Table(cols, tuple(rows))
