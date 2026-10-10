import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

def make_fact_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]

@dataclass(frozen=True)
class Provenance:
    accession: str; form: str; filed_date: str; fiscal_period: str
    fiscal_year: int; concept: str; source_url: str; xbrl_fact_url: str
    raw_value: str

@dataclass(frozen=True)
class Fact:
    fact_id: str; cik: int; ticker: str; company_name: str; value: Decimal
    unit: str; concept: str; period_start: date; period_end: date
    frame: str | None; provenance: Provenance

@dataclass(frozen=True)
class DerivedFact:
    fact_id: str; value: Decimal; formula: str; input_fact_ids: tuple[str, ...]

@dataclass(frozen=True)
class Company:
    ticker: str; cik: int; name: str

@dataclass(frozen=True)
class LineItem:
    alias: str; concepts: tuple[str, ...]; unit: str; scaling: str
    kind: str = "raw"; formula: str | None = None

@dataclass(frozen=True)
class PeriodSpec:
    type: str; n: int

@dataclass(frozen=True)
class QueryPlan:
    companies: tuple[Company, ...]; line_items: tuple[LineItem, ...]
    periods: PeriodSpec; outputs: tuple[str, ...]

@dataclass(frozen=True)
class Claim:
    id: str; text: str; evidence_ids: tuple[str, ...]; claim_type: str
