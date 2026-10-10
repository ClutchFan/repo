# Financial Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI agent that retrieves US tech-company financials from SEC XBRL, summarizes them, and exports cross-quarter comparison tables with cell-level provenance and verified claims.

**Architecture:** Plan–execute over a deterministic data layer. The LLM only parses intent and narrates supplied facts; code owns every number. Immutable `Fact`/`DerivedFact` objects carry provenance end to end; an independent verifier rejects unsupported narrative claims.

**Tech Stack:** Python 3.11+, httpx, openai, rich, openpyxl, pyyaml; stdlib decimal/dataclasses/sqlite/argparse; pytest + pytest-httpx for tests.

**Spec:** `docs/superpowers/specs/2026-10-10-financial-agent-design.md` (read alongside this plan).

## Global Constraints

- Python 3.11+; package root `finagent/`; tests in `tests/` mirroring package layout.
- Money/numeric values use `decimal.Decimal` everywhere; never `float`.
- SEC requests MUST send `User-Agent` containing a contact name and email; rate limit to ≤ 5 requests/second.
- Every external HTTP response is cached on disk (sqlite keyed by URL); tests never make live network calls (mock via pytest-httpx or load fixtures).
- `Fact` and `DerivedFact` are immutable (`frozen=True`, `Decimal`, hash-derived id).
- Bare numbers in LLM narrative output are forbidden; the verifier enforces this.
- Dependencies: `httpx`, `openai>=1.0`, `rich`, `openpyxl`, `pyyaml`, and dev `pytest`, `pytest-httpx`.
- Commit after every task; TDD: write failing test, watch it fail, implement, watch it pass.

---

## File Structure

```
pyproject.toml
finagent/
  __init__.py
  config.py
  models.py
  cache.py
  datasource/{__init__.py, sec_client.py, tickers.py, taxonomy.py, facts.py}
  metrics.py
  profile/{__init__.py, store.py}
  agent/{__init__.py, llm.py, tools.py, planner.py, loop.py}
  narrative/{__init__.py, summarizer.py, verifier.py}
  output/{__init__.py, table.py, xlsx.py, cli.py}
  app.py
  eval/{golden.yaml, run_eval.py}
tests/
  conftest.py
  fixtures/*.json
  datasource/test_*.py
  test_metrics.py test_models.py
  profile/test_store.py
  agent/test_*.py
  narrative/test_*.py
  output/test_*.py
```

Responsibilities: `models.py` = immutable data types; `cache.py` = sqlite HTTP cache; `sec_client.py` = throttled JSON HTTP; `tickers.py` = ticker→CIK; `taxonomy.py` = alias→concept fallback; `facts.py` = normalize/dedupe/align SEC payloads; `metrics.py` = deterministic derived facts; `profile/store.py` = JSON analyst profile; `agent/llm.py` = OpenAI structured-output wrapper; `agent/tools.py` = 4 read-only tools; `agent/planner.py` = plan validation; `agent/loop.py` = ReAct driver; `output/table.py` = aligned table; `narrative/summarizer.py` = claims from evidence; `narrative/verifier.py` = 3 gates; `output/{cli,xlsx}.py` = rendering; `app.py` = end-to-end orchestration + REPL.

---

## Task 1: Project scaffold and config

**Files:**
- Create: `pyproject.toml`, `finagent/__init__.py`, `finagent/config.py`, `tests/__init__.py`, `tests/conftest.py`, `.gitignore`

**Interfaces:**
- Produces: `finagent.config.Config` dataclass with fields `openai_api_key: str`, `sec_user_agent: str`, `cache_path: pathlib.Path`, `profile_path: pathlib.Path`, `model: str`; classmethod `Config.from_env(env: dict, sec_contact: tuple[str,str] | None = None) -> Config`.

- [ ] **Step 1: Write `pyproject.toml` and `.gitignore`**

`pyproject.toml`:
```toml
[project]
name = "finagent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["httpx", "openai>=1.0", "rich", "openpyxl", "pyyaml"]
[project.optional-dependencies]
dev = ["pytest", "pytest-httpx"]
[project.scripts]
finagent = "finagent.app:main"
[tool.pytest.ini_options]
testpaths = ["tests"]
```
`.gitignore`: `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.venv/`, `cache/`, `output/`, `.env`.

- [ ] **Step 2: Write the failing test** — `tests/test_config.py`
```python
import pytest
from finagent.config import Config

def test_config_from_env(monkeypatch, tmp_path):
    env = {"OPENAI_API_KEY": "sk-test"}
    cfg = Config.from_env(env, sec_contact=("Jane Doe", "jane@example.com"),
                          base_dir=tmp_path)
    assert cfg.openai_api_key == "sk-test"
    assert "jane@example.com" in cfg.sec_user_agent
    assert cfg.cache_path == tmp_path / "cache" / "http.sqlite"
    assert cfg.model  # non-empty default

def test_config_requires_contact(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        Config.from_env({"OPENAI_API_KEY": "x"}, base_dir=tmp_path)
```

- [ ] **Step 3: Run and verify failure**
Run: `pip install -e '.[dev]' && pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: finagent`.

- [ ] **Step 4: Implement** — `finagent/config.py`
```python
import os, pathlib
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    openai_api_key: str
    sec_user_agent: str
    cache_path: pathlib.Path
    profile_path: pathlib.Path
    model: str

    @classmethod
    def from_env(cls, env, sec_contact=None, base_dir=None):
        base_dir = pathlib.Path(base_dir or os.getcwd())
        if not sec_contact:
            raise ValueError("SEC contact name and email are required")
        name, email = sec_contact
        key = env.get("OPENAI_API_KEY", "")
        return cls(
            openai_api_key=key,
            sec_user_agent=f"{name} {email}",
            cache_path=base_dir / "cache" / "http.sqlite",
            profile_path=pathlib.Path.home() / ".finagent" / "profile.json",
            model=env.get("FINAGENT_MODEL", "gpt-4o"),
        )
```
Also create empty `finagent/__init__.py` and `tests/__init__.py`; minimal `tests/conftest.py` now (fixtures added later).

- [ ] **Step 5: Run and verify pass**
Run: `pytest tests/test_config.py -v` → Expected PASS.

- [ ] **Step 6: Commit**
```bash
git add pyproject.toml .gitignore finagent tests && git commit -m "chore: scaffold package and config"
```

---

## Task 2: Core immutable models

**Files:**
- Create: `finagent/models.py`; Test: `tests/test_models.py`

**Interfaces:**
- Produces (used by all later tasks):
```python
@dataclass(frozen=True) class Provenance: accession, form, filed_date, fiscal_period, fiscal_year, concept, source_url, xbrl_fact_url, raw_value  (all str; fiscal_year int)
@dataclass(frozen=True) class Fact: fact_id:str; cik:int; ticker:str; company_name:str; value:Decimal; unit:str; concept:str; period_start:date; period_end:date; frame:str|None; provenance:Provenance
@dataclass(frozen=True) class DerivedFact: fact_id:str; value:Decimal; formula:str; input_fact_ids:tuple[str,...]
@dataclass(frozen=True) class Company: ticker:str; cik:int; name:str
@dataclass(frozen=True) class LineItem: alias:str; concepts:tuple[str,...]; unit:str; scaling:str; kind:str="raw"; formula:str|None=None
@dataclass(frozen=True) class PeriodSpec: type:str; n:int
@dataclass(frozen=True) class QueryPlan: companies:tuple[Company,...]; line_items:tuple[LineItem,...]; periods:PeriodSpec; outputs:tuple[str,...]
@dataclass(frozen=True) class Claim: id:str; text:str; evidence_ids:tuple[str,...]; claim_type:str  # "datapoint"|"interpretation"
def make_fact_id(*parts: str) -> str  # sha1 of "|".join(parts)[:16]
```

- [ ] **Step 1: Write the failing test**
```python
import pytest
from decimal import Decimal
from datetime import date
from finagent.models import Fact, Provenance, DerivedFact, make_fact_id

def _prov(**kw):
    base = dict(accession="a", form="10-Q", filed_date="2024-02-02",
                fiscal_period="Q1", fiscal_year=2024, concept="us-gaap:Revenues",
                source_url="u", xbrl_fact_url="x", raw_value="1000")
    base.update(kw); return Provenance(**base)

def test_fact_is_immutable():
    f = Fact(make_fact_id("f"), 1, "X", "X Co", Decimal("1000"), "USD",
             "us-gaap:Revenues", date(2024,1,1), date(2024,3,31), "CY2024Q1", _prov())
    with pytest.raises(Exception):
        f.value = Decimal("2")  # type: ignore

def test_fact_id_deterministic():
    assert make_fact_id("a","b") == make_fact_id("a","b")
    assert make_fact_id("a") != make_fact_id("b")
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_models.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement** — `finagent/models.py`
```python
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
```

- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit**
```bash
git add finagent/models.py tests/test_models.py && git commit -m "feat: add immutable core models"
```

---

## Task 3: SQLite HTTP cache

**Files:**
- Create: `finagent/cache.py`; Test: `tests/test_cache.py`

**Interfaces:**
- Produces: `class ResponseCache: def __init__(self, path: pathlib.Path); def get(self, url:str)->str|None; def set(self, url:str, body:str)->None`. Table `http(url TEXT PRIMARY KEY, body TEXT)`. Creates parent dir.

- [ ] **Step 1: Failing test**
```python
from finagent.cache import ResponseCache
def test_roundtrip(tmp_path):
    c = ResponseCache(tmp_path / "c.sqlite")
    assert c.get("http://x") is None
    c.set("http://x", "{}")
    assert c.get("http://x") == "{}"
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
```python
import sqlite3, pathlib
class ResponseCache:
    def __init__(self, path):
        self.path = pathlib.Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.path)
        self._con.execute("CREATE TABLE IF NOT EXISTS http(url TEXT PRIMARY KEY, body TEXT)")
        self._con.commit()
    def get(self, url):
        row = self._con.execute("SELECT body FROM http WHERE url=?", (url,)).fetchone()
        return row[0] if row else None
    def set(self, url, body):
        self._con.execute("INSERT OR REPLACE INTO http(url,body) VALUES(?,?)", (url, body))
        self._con.commit()
```

- [ ] **Step 4: Verify pass, then commit**
```bash
git add finagent/cache.py tests/test_cache.py && git commit -m "feat: add sqlite http cache"
```

---

## Task 4: SEC HTTP client (rate limit, UA, cache)

**Files:**
- Create: `finagent/datasource/__init__.py`, `finagent/datasource/sec_client.py`; Test: `tests/datasource/test_sec_client.py`; fixture helper.

**Interfaces:**
- Consumes: `ResponseCache`.
- Produces:
```python
class SECClient:
    def __init__(self, user_agent:str, cache:ResponseCache, client:httpx.Client|None=None, min_interval:float=0.2): ...
    BASE = "https://data.sec.gov"
    def get_json(self, path:str) -> dict        # path like "/api/xbrl/companyfacts/CIK0000320193.json"
    def get_company_facts(self, cik:int) -> dict
    def get_submissions(self, cik:int) -> dict
    def get_ticker_index(self) -> list[dict]     # /files/company_tickers.json on www.sec.gov
```
Rules: header `User-Agent=user_agent` and `Accept-Encoding: gzip, deflate`; cache-first (no network on hit); enforce minimum interval between live calls with a simple time gate (tests pass `min_interval=0`).

- [ ] **Step 1: Failing test (mock HTTP with pytest-httpx)**
```python
import httpx, pytest
from finagent.cache import ResponseCache
from finagent.datasource.sec_client import SECClient

def test_get_json_caches_and_headers(httpx_mock, tmp_path):
    httpx_mock.add_response(url="https://data.sec.gov/x.json", json={"ok": True})
    cache = ResponseCache(tmp_path / "c.sqlite")
    c = SECClient("Jane jane@example.com", cache, min_interval=0)
    assert c.get_json("/x.json") == {"ok": True}
    assert c.get_json("/x.json") == {"ok": True}  # second served from cache
    req = httpx_mock.get_requests()
    assert len(req) == 1
    assert "jane@example.com" in req[0].headers["user-agent"]
```

- [ ] **Step 2: Run, verify fail** (import error).
- [ ] **Step 3: Implement** — `sec_client.py`
```python
import time, httpx
class SECClient:
    BASE = "https://data.sec.gov"
    WWW = "https://www.sec.gov"
    def __init__(self, user_agent, cache, client=None, min_interval=0.2):
        self._ua = user_agent; self._cache = cache
        self._http = client or httpx.Client(headers={
            "User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self._min_interval = min_interval; self._last = 0.0
    def _throttle(self):
        if self._min_interval:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0: time.sleep(wait)
        self._last = time.monotonic()
    def get_json(self, path):
        url = path if path.startswith("http") else f"{self.BASE}{path}"
        hit = self._cache.get(url)
        if hit is not None:
            import json; return json.loads(hit)
        self._throttle()
        r = self._http.get(url); r.raise_for_status()
        self._cache.set(url, r.text)
        return r.json()
    def get_company_facts(self, cik):
        return self.get_json(f"/api/xbrl/companyfacts/CIK{int(cik):010d}.json")
    def get_submissions(self, cik):
        return self.get_json(f"/submissions/CIK{int(cik):010d}.json")
    def get_ticker_index(self):
        data = self.get_json(f"{self.WWW}/files/company_tickers.json")
        return list(data.values())
```
Create empty `finagent/datasource/__init__.py`; add `tests/datasource/__init__.py`.

- [ ] **Step 4: Verify pass; ensure cache-hit makes only one request.** Then commit
```bash
git add finagent/datasource tests/datasource && git commit -m "feat: add cached, throttled SEC client"
```

---

## Task 5: Ticker → CIK resolution

**Files:**
- Create: `finagent/datasource/tickers.py`; Test: `tests/datasource/test_tickers.py`

**Interfaces:**
- Consumes: `SECClient.get_ticker_index()`.
- Produces:
```python
class TickerResolver:
    def __init__(self, sec: SECClient): ...
    def resolve(self, text:str) -> Company            # exact/upper ticker; raises AmbiguousTicker with candidates on miss
    def candidates(self, text:str) -> list[Company]
class AmbiguousTicker(Exception): def __init__(self, text, candidates:list[Company])
```
Index records shaped `{"ticker":"AAPL","cik":320193,"title":"Apple Inc."}`. Exact match (case-insensitive) returns `Company`. Name-substring search provides candidates; exact ticker always wins.

- [ ] **Step 1: Failing test**
```python
import pytest
from finagent.datasource.tickers import TickerResolver, AmbiguousTicker
from finagent.models import Company

class FakeSEC:
    def get_ticker_index(self):
        return [{"ticker":"AAPL","cik":320193,"title":"Apple Inc."},
                {"ticker":"MSFT","cik":789019,"title":"Microsoft Corp."}]

def test_exact_ticker():
    r = TickerResolver(FakeSEC())
    assert r.resolve("aapl") == Company("AAPL", 320193, "Apple Inc.")

def test_miss_is_ambiguous():
    r = TickerResolver(FakeSEC())
    with pytest.raises(AmbiguousTicker) as e:
        r.resolve("apple")
    assert Company("AAPL", 320193, "Apple Inc.") in e.value.candidates
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**
```python
from finagent.models import Company
class AmbiguousTicker(Exception):
    def __init__(self, text, candidates):
        super().__init__(f"ambiguous: {text}"); self.text=text; self.candidates=candidates
class TickerResolver:
    def __init__(self, sec): self._sec=sec; self._rows=None
    def _index(self):
        if self._rows is None: self._rows=self._sec.get_ticker_index()
        return self._rows
    def candidates(self, text):
        t=text.strip().lower(); out=[]
        for row in self._index():
            if t==row["ticker"].lower() or t in row["title"].lower():
                out.append(Company(row["ticker"], int(row["cik"]), row["title"]))
        return out
    def resolve(self, text):
        for row in self._index():
            if text.strip().lower()==row["ticker"].lower():
                return Company(row["ticker"], int(row["cik"]), row["title"])
        c=self.candidates(text)
        if len(c)==1: return c[0]
        raise AmbiguousTicker(text, c)
```

- [ ] **Step 4: Verify pass, commit**
```bash
git add finagent/datasource/tickers.py tests/datasource/test_tickers.py && git commit -m "feat: add ticker to CIK resolution"
```

---

## Task 6: Taxonomy alias mapping

**Files:**
- Create: `finagent/datasource/taxonomy.py`, `finagent/datasource/default_metrics.yaml`; Test: `tests/datasource/test_taxonomy.py`

**Interfaces:**
- Produces:
```python
METRIC_ALIASES: dict[str, tuple[str,...]]   # loaded from yaml
def concepts_for(alias:str) -> tuple[str,...]              # KeyError if unknown
def pick_concept(alias:str, available:set[str]) -> str|None  # first fallback present
```
YAML maps alias to ordered list; include: revenue → `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`; gross_profit → `GrossProfit`; net_income → `NetIncomeLoss`; operating_income → `OperatingIncomeLoss`. All prefixed `us-gaap:` in code, yaml stores bare names.

- [ ] **Step 1: Failing test**
```python
from finagent.datasource.taxonomy import concepts_for, pick_concept
def test_fallback_order():
    cs = concepts_for("revenue")
    assert cs[0].endswith("RevenueFromContractWithCustomerExcludingAssessedTax")
    assert pick_concept("revenue", {"us-gaap:Revenues"}) == "us-gaap:Revenues"
    assert pick_concept("revenue", {"us-gaap:Other"}) is None
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — yaml file:
```yaml
revenue: [RevenueFromContractWithCustomerExcludingAssessedTax, Revenues]
gross_profit: [GrossProfit]
net_income: [NetIncomeLoss]
operating_income: [OperatingIncomeLoss]
```
`taxonomy.py`:
```python
import pathlib, yaml
_p = pathlib.Path(__file__).with_name("default_metrics.yaml")
_raw = yaml.safe_load(_p.read_text())
METRIC_ALIASES = {k: tuple(f"us-gaap:{n}" for n in v) for k, v in _raw.items()}
def concepts_for(alias):
    return METRIC_ALIASES[alias]
def pick_concept(alias, available):
    for c in concepts_for(alias):
        if c in available: return c
    return None
```

- [ ] **Step 4: Verify pass, commit**
```bash
git add finagent/datasource/taxonomy.py finagent/datasource/default_metrics.yaml tests/datasource/test_taxonomy.py && git commit -m "feat: add metric alias taxonomy with concept fallback"
```

---

## Task 7: Normalize SEC companyfacts into Facts

**Files:**
- Create: `finagent/datasource/facts.py`; Test: `tests/datasource/test_facts.py`; fixture `tests/fixtures/companyfacts_small.json`.

**Interfaces:**
- Consumes: `Fact`, `Provenance`, `make_fact_id`.
- Produces:
```python
def fact_urls(cik:int, accession:str) -> tuple[str,str]  # (filing browse url, xbrl viewer url)
def normalize_company_facts(payload:dict) -> list[Fact]
def available_concepts(facts:list[Fact]) -> set[str]
def facts_for_concept(facts:list[Fact], concept:str) -> list[Fact]
```
Payload shape: `{"entityName":..,"cik":320193,"facts":{"us-gaap":{"<Concept>":{"units":{"USD":[{"val":119580000000,"start":"2024-01-01","end":"2024-03-31","fy":2024,"fp":"Q1","form":"10-Q","filed":"2024-05-03","acc":"0000320193-24-000006","frame":"CY2024Q1"}]}}}}}`. Each unit entry → Fact (only entries with `acc`/`filed`/`form`; duration concepts have start/end; instant concepts use end for both). `fact_id=make_fact_id(ticker,concept,unit,start,end,acc,val)`.

- [ ] **Step 1: Fixture** — `tests/fixtures/companyfacts_small.json`
```json
{"entityName":"Apple Inc.","cik":320193,"ticker":"AAPL",
 "facts":{"us-gaap":{
   "Revenues":{"units":{"USD":[
     {"val":119580000000,"start":"2023-12-31","end":"2024-03-30","fy":2024,"fp":"Q2","form":"10-Q","filed":"2024-05-03","acc":"0000320193-24-000006","frame":"CY2024Q1"}]}},
   "GrossProfit":{"units":{"USD":[
     {"val":54000000000,"start":"2023-12-31","end":"2024-03-30","fy":2024,"fp":"Q2","form":"10-Q","filed":"2024-05-03","acc":"0000320193-24-000006","frame":"CY2024Q1"}]}}}}}
```

- [ ] **Step 2: Failing test**
```python
import json, pathlib
from decimal import Decimal
from finagent.datasource.facts import normalize_company_facts, available_concepts, facts_for_concept
FIX = pathlib.Path(__file__).parent.parent / "fixtures" / "companyfacts_small.json"
def test_normalize():
    facts = normalize_company_facts(json.loads(FIX.read_text()))
    assert len(facts) == 2
    rev = [f for f in facts if f.concept.endswith("Revenues")][0]
    assert rev.value == Decimal("119580000000")
    assert rev.ticker == "AAPL" and rev.cik == 320193 and rev.frame == "CY2024Q1"
    assert rev.provenance.accession == "0000320193-24-000006"
    assert rev.provenance.source_url.startswith("https://www.sec.gov/")
    assert "us-gaap:Revenues" in available_concepts(facts)
    assert len(facts_for_concept(facts, "us-gaap:Revenues")) == 1
```

- [ ] **Step 3: Run, verify fail.**
- [ ] **Step 4: Implement** — `facts.py`
```python
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
```

- [ ] **Step 5: Verify pass, commit**
```bash
git add finagent/datasource/facts.py tests && git commit -m "feat: normalize SEC companyfacts into immutable facts"
```

---

## Task 8: Revision dedup, YTD differencing, quarter alignment

**Files:**
- Modify: `finagent/datasource/facts.py`; Test: `tests/datasource/test_alignment.py`

**Interfaces:**
- Produces:
```python
def latest_per_period(facts:list[Fact]) -> dict[tuple[str,date], Fact]
    # key=(concept, period_end); keep entry whose provenance.filed_date is greatest
def duration_days(f:Fact)->int
def single_quarters(facts:list[Fact]) -> list[Fact]
    # split YTD cumulative duration facts into single-quarter facts via subtraction:
    # for same concept & fiscal year, Q2 = H1 - Q1, Q3 = 9M - H1; returns originals for ~90d + derived-as-Fact? No—returns Fact list with provenance of the cumulative filing and fact_id noting diff.
def align_frame(facts:list[Fact]) -> dict[str, list[Fact]]   # frame -> facts
```
Note: differencing needs cumulative facts for the same concept. Implement by sorting duration facts by period length and subtracting adjacent prefixes of the same fiscal year; produced single-quarter facts are plain `Fact` objects whose `raw_value` is `"derived:YTD_DIFF"` and whose provenance is the longer cumulative filing (deterministic; a DerivedFact chain is recorded in metrics layer at table time — here keep it simple and honest: set `frame` from the calendar end when computable).

- [ ] **Step 1: Failing test**
```python
from datetime import date
from decimal import Decimal
from finagent.models import Fact, Provenance, make_fact_id
from finagent.datasource.facts import latest_per_period, single_quarters

def prov(filed, acc="a"):
    return Provenance(acc,"10-Q",filed,"Q2",2024,"us-gaap:Revenues","u","x","0")
def fact(val, start, end, filed, frame=None):
    return Fact(make_fact_id(str(start),str(end),filed,str(val)),320193,"AAPL","Apple",
        Decimal(val),"USD","us-gaap:Revenues",date.fromisoformat(start),date.fromisoformat(end),frame,prov(filed))

def test_latest_wins():
    old = fact("100","2024-01-01","2024-03-31","2024-04-01")
    new = fact("110","2024-01-01","2024-03-31","2024-06-01")
    m = latest_per_period([old,new])
    assert m[("us-gaap:Revenues", date(2024,3,31))].value == Decimal("110")

def test_ytd_difference():
    q1 = fact("100","2024-01-01","2024-03-31","2024-04-01","CY2024Q1")
    h1 = fact("230","2024-01-01","2024-06-30","2024-07-01","CY2024H1")
    qs = single_quarters([q1,h1])
    by_end = {f.period_end: f for f in qs}
    assert by_end[date(2024,3,31)].value == Decimal("100")
    assert by_end[date(2024,6,30)].value == Decimal("130")  # 230-100
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (append to `facts.py`)
```python
def latest_per_period(facts):
    out = {}
    for f in facts:
        key=(f.concept, f.period_end)
        cur=out.get(key)
        if cur is None or f.provenance.filed_date > cur.provenance.filed_date:
            out[key]=f
    return out

def duration_days(f):
    return (f.period_end - f.period_start).days

def single_quarters(facts):
    result=[f for f in facts]
    by_concept_year={}
    for f in facts:
        if f.provenance.fiscal_year:
            by_concept_year.setdefault((f.concept,f.provenance.fiscal_year),[]).append(f)
    for key, group in by_concept_year.items():
        cums = sorted([g for g in group if duration_days(g) > 120],
                      key=lambda g: duration_days(g))
        quarters = sorted([g for g in group if duration_days(g) <= 120],
                          key=lambda g: g.period_end)
        for cum in cums:
            prior_end = max((q.period_end for q in quarters if q.period_end < cum.period_end),
                            default=None)
            # prior cumulative prefix = longest fact ending before this cumulative end
            prefix = None
            for g in group:
                if g.period_start == cum.period_start and g.period_end < cum.period_end and \
                   (prefix is None or g.period_end > prefix.period_end):
                    prefix = g
            if prefix is None: continue
            val = cum.value - prefix.value
            fid = make_fact_id("YTDDIFF", cum.fact_id, prefix.fact_id)
            start = prefix.period_end.fromordinal(prefix.period_end.toordinal()+1)
            p = cum.provenance
            import dataclasses
            newprov = dataclasses.replace(p, raw_value="derived:YTD_DIFF")
            q = Fact(fid, cum.cik, cum.ticker, cum.company_name, val, cum.unit,
                     cum.concept, start, cum.period_end, None, newprov)
            result.append(q); quarters.append(q)
    # dedupe by (concept,end) preferring shortest duration / derived last
    final={}
    for f in result:
        final.setdefault((f.concept,f.period_end), f)
    return list(final.values())

def align_frame(facts):
    out={}
    for f in facts:
        if f.frame: out.setdefault(f.frame,[]).append(f)
    return out
```
(Note: derived quarter facts are exposed in the metrics layer as `DerivedFact` too — handled Task 9 at table build using the `raw_value == "derived:YTD_DIFF"` marker.)

- [ ] **Step 4: Verify pass, commit**
```bash
git add finagent/datasource/facts.py tests/datasource/test_alignment.py && git commit -m "feat: revision dedup and YTD-to-quarter differencing"
```

---

## Task 9: Deterministic derived metrics

**Files:**
- Create: `finagent/metrics.py`; Test: `tests/test_metrics.py`

**Interfaces:**
- Produces:
```python
def ratio(numerator:Fact, denominator:Fact) -> DerivedFact       # value rounded 6dp
def yoy(current:Fact, year_ago:Fact) -> DerivedFact               # (cur-prev)/prev
def scale_value(value:Decimal, scaling:str) -> Decimal            # "millions"/"billions"/"raw"
SCALINGS = ("raw","thousands","millions","billions")
```
`fact_id=make_fact_id(formula, *input_ids)`.

- [ ] **Step 1: Failing test**
```python
from decimal import Decimal
from finagent.metrics import ratio, yoy, scale_value
from finagent.models import Fact, Provenance, make_fact_id
from datetime import date
def f(v): return Fact(make_fact_id(v),1,"T","T",Decimal(v),"USD","c",
    date(2024,1,1),date(2024,3,31),None,Provenance("a","10-Q","d","Q1",2024,"c","u","x","0"))
def test_ratio():
    d=ratio(f("50"),f("100")); assert d.value==Decimal("0.5") and d.formula=="ratio"
    assert len(d.input_fact_ids)==2
def test_yoy():
    assert yoy(f("105"),f("100")).value==Decimal("0.05")
def test_scale():
    assert scale_value(Decimal("119580000000"),"millions")==Decimal("119580")
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement**
```python
from decimal import Decimal, ROUND_HALF_UP
from finagent.models import DerivedFact, make_fact_id
_S={"raw":1,"thousands":1e3,"millions":1e6,"billions":1e9}
SCALINGS=tuple(_S)
def _d(x): return Decimal(str(x))
def ratio(a,b):
    return DerivedFact(make_fact_id("ratio",a.fact_id,b.fact_id),
        (a.value/b.value).quantize(Decimal("0.000001"),ROUND_HALF_UP),"ratio",
        (a.fact_id,b.fact_id))
def yoy(cur,prev):
    return DerivedFact(make_fact_id("yoy",cur.fact_id,prev.fact_id),
        ((cur.value-prev.value)/prev.value).quantize(Decimal("0.000001"),ROUND_HALF_UP),
        "yoy",(cur.fact_id,prev.fact_id))
def scale_value(value, scaling):
    return (value/_d(_S[scaling])).quantize(Decimal("0.01"),ROUND_HALF_UP)
```

- [ ] **Step 4: Verify pass, commit**
```bash
git add finagent/metrics.py tests/test_metrics.py && git commit -m "feat: deterministic derived metrics and scaling"
```

---

## Task 10: Analyst profile store

**Files:**
- Create: `finagent/profile/__init__.py`, `finagent/profile/store.py`; Test: `tests/profile/test_store.py`

**Interfaces:**
- Produces:
```python
@dataclass class Profile: watchlist:list[Company]; metric_aliases:dict[str,str]; default_quarters:int; preferences:dict; confirmed_resolutions:dict[str,str]
class ProfileStore:
    def __init__(self, path:pathlib.Path): ...
    def load(self)->Profile                       # empty defaults if missing
    def save(self, p:Profile)->None
    def apply_update(self, update:ProfileUpdate)->Profile  # validates then writes
@dataclass class ProfileUpdate: add_watchlist:list[Company]=...; set_alias:tuple[str,str]|None=None; set_quarters:int|None=None
```

- [ ] **Step 1: Failing test**
```python
from finagent.profile.store import ProfileStore, ProfileUpdate
from finagent.models import Company
def test_defaults_and_update(tmp_path):
    s=ProfileStore(tmp_path/"p.json"); p=s.load()
    assert p.default_quarters==4 and p.watchlist==[]
    p=s.apply_update(ProfileUpdate(add_watchlist=[Company("NVDA",1045810,"NVIDIA")],
                                   set_alias=("收入","revenue"), set_quarters=2))
    assert p.watchlist==[Company("NVDA",1045810,"NVIDIA")]
    assert p.metric_aliases["收入"]=="revenue" and p.default_quarters==2
    assert ProfileStore(tmp_path/"p.json").load().default_quarters==2  # persisted
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement**
```python
import json, pathlib, dataclasses
from dataclasses import dataclass, field, asdict
from finagent.models import Company
@dataclass
class Profile:
    watchlist: list=field(default_factory=list)
    metric_aliases: dict=field(default_factory=dict)
    default_quarters: int=4
    preferences: dict=field(default_factory=lambda:{"units":"USD","scaling":"millions"})
    confirmed_resolutions: dict=field(default_factory=dict)
@dataclass
class ProfileUpdate:
    add_watchlist: list=field(default_factory=list)
    set_alias: tuple|None=None
    set_quarters: int|None=None
class ProfileStore:
    def __init__(self,path): self.path=pathlib.Path(path)
    def load(self):
        if not self.path.exists(): return Profile()
        d=json.loads(self.path.read_text())
        w=[Company(**c) for c in d.get("watchlist",[])]
        return Profile(w,d.get("metric_aliases",{}),d.get("default_quarters",4),
                       d.get("preferences",{"units":"USD","scaling":"millions"}),
                       d.get("confirmed_resolutions",{}))
    def save(self,p):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        d=asdict(p); d["watchlist"]=[asdict(c) for c in p.watchlist]
        self.path.write_text(json.dumps(d,ensure_ascii=False,indent=2))
    def apply_update(self,u):
        p=self.load()
        for c in u.add_watchlist:
            if c not in p.watchlist: p.watchlist.append(c)
        if u.set_alias: p.metric_aliases[u.set_alias[0]]=u.set_alias[1]
        if u.set_quarters: p.default_quarters=u.set_quarters
        self.save(p); return p
```
Add `finagent/profile/__init__.py` and `tests/profile/__init__.py`.

- [ ] **Step 4: Verify pass, commit**
```bash
git add finagent/profile tests/profile && git commit -m "feat: add persisted analyst profile"
```

---

## Task 11: LLM structured-output wrapper

**Files:**
- Create: `finagent/agent/__init__.py`, `finagent/agent/llm.py`; Test: `tests/agent/test_llm.py`

**Interfaces:**
- Consumes: OpenAI client (injected).
- Produces:
```python
class LLMClient:
    def __init__(self, openai_client, model:str): ...
    def complete_json(self, system:str, messages:list[dict], schema:dict,
                      tools:list[dict]|None=None) -> dict
        # calls chat.completions.create with response_format json_schema strict; returns parsed dict.
        # A fake client is injected in tests.
```
Define JSON schemas `PLAN_SCHEMA`, `CLAIMS_SCHEMA`, `VERDICT_SCHEMA` as module constants (used Tasks 12–14).

- [ ] **Step 1: Failing test with a fake OpenAI client**
```python
from finagent.agent.llm import LLMClient
class FakeMsg:
    def __init__(self,c): self.content=c
class FakeChoice:
    def __init__(self,c): self.message=FakeMsg(c)
class FakeResp:
    def __init__(self,c): self.choices=[FakeChoice(c)]
class FakeChat:
    def create(self,**kw): return FakeResp('{"value": 42}')
class FakeCompletions: chat=type("C",(),{"completions":FakeChat()})()
class FakeOpenAI:
    def __init__(self): self.chat=FakeCompletions().chat
def test_complete_json():
    c=LLMClient(FakeOpenAI(),"gpt-4o")
    assert c.complete_json("sys",[{"role":"user","content":"hi"}],
                           {"type":"object"}) == {"value":42}
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement**
```python
import json
PLAN_SCHEMA = {"type":"object"}   # full schema supplied in Task 12 constants
CLAIMS_SCHEMA = {"type":"object"}
VERDICT_SCHEMA = {"type":"object"}
class LLMClient:
    def __init__(self, openai_client, model):
        self._c=openai_client; self.model=model
    def complete_json(self, system, messages, schema, tools=None):
        resp=self._c.chat.completions.create(
            model=self.model,
            messages=[{"role":"system","content":system}]+messages,
            response_format={"type":"json_schema","json_schema":{
                "name":"result","strict":True,"schema":schema}},
            tools=tools or None)
        return json.loads(resp.choices[0].message.content)
```
Add `tests/agent/__init__.py`.

- [ ] **Step 4: Verify pass, commit**
```bash
git add finagent/agent tests/agent && git commit -m "feat: add openai structured-output wrapper"
```

---

## Task 12: Read-only agent tools and plan validation

**Files:**
- Create: `finagent/agent/tools.py`, `finagent/agent/planner.py`; Test: `tests/agent/test_tools.py`, `tests/agent/test_planner.py`

**Interfaces from earlier tasks:** `SECClient`, `TickerResolver`, `normalize_company_facts`, `available_concepts`, `single_quarters`, `pick_concept`, models.
- Produces:
```python
class DataTools:
    def __init__(self, sec, resolver): ...          # caches facts per cik
    def resolve_ticker(self, t:str)->dict           # {ok, company?} or {ok:False,candidates:[...]}
    def list_concepts(self, cik:int, query:str)->dict
    def list_available_periods(self, cik:int)->dict
    def preview_metric(self, cik:int, concept:str)->dict
    def call(self, name:str, args:dict)->dict        # dispatch; KeyError->error dict
def validate_plan(plan:QueryPlan, known:dict[tuple[Company], set[concepts]]) -> list[str]
    # returns list of error strings; empty = valid. Checks: cik resolved; concepts filed;
    # derived inputs present; periods within available.
```

- [ ] **Step 1: Failing test — tools**
```python
from finagent.agent.tools import DataTools
class FakeSEC:
    def get_ticker_index(self): return [{"ticker":"AAPL","cik":320193,"title":"Apple Inc."}]
    def get_company_facts(self,cik):
        return {"cik":320193,"ticker":"AAPL","entityName":"Apple Inc.","facts":{
          "us-gaap":{"Revenues":{"units":{"USD":[
            {"val":1,"start":"2024-01-01","end":"2024-03-31","form":"10-Q",
             "filed":"2024-05-01","acc":"0000320193-24-000006","frame":"CY2024Q1"}]}}}}}
from finagent.datasource.tickers import TickerResolver
def test_resolve_and_concepts():
    dt=DataTools(FakeSEC(), TickerResolver(FakeSEC()))
    r=dt.call("resolve_ticker",{"ticker":"AAPL"})
    assert r["ok"] and r["company"]["cik"]==320193
    c=dt.call("list_concepts",{"cik":320193,"query":"revenue"})
    assert any("Revenues" in x for x in c["concepts"])
    p=dt.call("list_available_periods",{"cik":320193})
    assert "CY2024Q1" in p["frames"]
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement `tools.py`**
```python
from dataclasses import asdict
from finagent.datasource.tickers import AmbiguousTicker
from finagent.datasource.facts import (normalize_company_facts, available_concepts,
    facts_for_concept, single_quarters, align_frame)
class DataTools:
    def __init__(self, sec, resolver):
        self.sec=sec; self.resolver=resolver; self._facts={}
    def _facts_for(self,cik):
        if cik not in self._facts:
            self._facts[cik]=normalize_company_facts(self.sec.get_company_facts(cik))
        return self._facts[cik]
    def resolve_ticker(self,t):
        try: c=self.resolver.resolve(t); return {"ok":True,"company":asdict(c)}
        except AmbiguousTicker as e:
            return {"ok":False,"candidates":[asdict(x) for x in e.candidates]}
    def list_concepts(self,cik,query):
        q=query.lower(); cs=sorted(c for c in available_concepts(self._facts_for(cik)) if q in c.lower())
        return {"concepts":cs}
    def list_available_periods(self,cik):
        fs=single_quarters(self._facts_for(cik))
        return {"frames":sorted({f.frame for f in fs if f.frame})}
    def preview_metric(self,cik,concept):
        fs=facts_for_concept(self._facts_for(cik),concept)
        if not fs: return {"ok":False,"reason":"not reported"}
        f=sorted(fs,key=lambda x:x.period_end)[-1]
        return {"ok":True,"value":str(f.value),"unit":f.unit,"frame":f.frame,
                "accession":f.provenance.accession}
    def call(self,name,args):
        fn=getattr(self,name,None)
        if fn is None: return {"ok":False,"error":f"unknown tool {name}"}
        try: return fn(**args)
        except TypeError as e: return {"ok":False,"error":str(e)}
```

- [ ] **Step 4: Failing test — planner validation**
```python
from finagent.agent.planner import validate_plan
from finagent.models import Company, LineItem, PeriodSpec, QueryPlan
AAPL=Company("AAPL",320193,"Apple Inc.")
def plan(concepts=("us-gaap:Revenues",)):
    return QueryPlan((AAPL,),(LineItem("revenue",concepts,"USD","millions"),),
                     PeriodSpec("last_n_quarters",1),("table",))
def test_unknown_concept_rejected():
    errs=validate_plan(plan(("us-gaap:Nope",)), {AAPL:{"us-gaap:Revenues"},"frames":{"CY2024Q1"}})
    assert any("concept" in e for e in errs)
def test_valid_plan():
    errs=validate_plan(plan(), {AAPL:{"us-gaap:Revenues"},"frames":{"CY2024Q1"}})
    assert errs==[]
```

- [ ] **Step 5: Verify fail, implement `planner.py`**
```python
from finagent.datasource.taxonomy import pick_concept
def validate_plan(plan, known):
    errs=[]
    for comp in plan.companies:
        info=next((v for k,v in known.items() if getattr(k,"cik",None)==comp.cik), None)
        if info is None:
            errs.append(f"unresolved company {comp.ticker}"); continue
        concepts=info if isinstance(info,set) else info.get("concepts",set())
        for li in plan.line_items:
            if li.kind=="raw":
                if not any(c in concepts for c in li.concepts):
                    errs.append(f"{comp.ticker}: concept unavailable for {li.alias}")
        frames = known.get("frames",set())
        if plan.periods.type=="last_n_quarters" and not frames:
            errs.append(f"{comp.ticker}: no quarterly frames available")
    return errs
```
(The derived-input check is enforced where tables are built, Task 13; the formula whitelist lives in `metrics.py` consumers.)

- [ ] **Step 6: Verify both pass, commit**
```bash
git add finagent/agent/tools.py finagent/agent/planner.py tests/agent && git commit -m "feat: read-only data tools and plan validation"
```

---

## Task 13: ReAct loop, fetch orchestration, table builder

**Files:**
- Create: `finagent/agent/loop.py`, `finagent/output/__init__.py`, `finagent/output/table.py`; Test: `tests/agent/test_loop.py`, `tests/output/test_table.py`

**Interfaces:**
- Consumes: `LLMClient`, `DataTools`, `validate_plan`, models, `single_quarters`, `metrics`.
- Produces:
```python
class AgentLoop:
    def __init__(self, llm, tools, max_turns=6): ...
    def run(self, question:str, profile_summary:str) -> QueryPlan
       # model returns {"tool":name,"args":{...}} or {"final": <plan dict>};
       # parses plan dict into QueryPlan; validates; on error feeds {"error":...} and retries.
def build_table(plan, facts_by_company:dict[Company,list[Fact]]) -> Table
@dataclass Table: columns:tuple[str,...]  # frames chronological
                 rows: tuple[TableRow,...]
@dataclass TableRow: company:str; alias:str; scaling:str;
                     cells: tuple[Cell,...]; formula:str|None
@dataclass Cell: frame:str; value:Decimal|None; fact_id:str|None; note:str=""
```
`build_table`: choose last N frames from the union; for raw line item pick concept via `pick_concept`; find single-quarter fact for frame; scale value (`metrics.scale_value`); N/A with note when absent. Derived items (`gross_margin`) computed from named input aliases that must also be in the plan — reject otherwise.

- [ ] **Step 1: Failing table test**
```python
from datetime import date
from decimal import Decimal
from finagent.output.table import build_table
from finagent.models import Company, LineItem, PeriodSpec, QueryPlan, Fact, Provenance, make_fact_id
A=Company("AAPL",320193,"Apple")
def fact(frame,val,concept="us-gaap:Revenues"):
    return Fact(make_fact_id(frame,concept,val),320193,"AAPL","Apple",Decimal(val),"USD",
      concept,date(2024,1,1),date(2024,3,31),frame,
      Provenance("a","10-Q","d","Q1",2024,concept,"u","x","0"))
def plan(items): return QueryPlan((A,),items,PeriodSpec("last_n_quarters",1),("table",))
def test_raw_row_and_missing():
    li=LineItem("revenue",("us-gaap:Revenues",),"USD","millions")
    t=build_table(plan((li,)), {A:[fact("CY2024Q1","119580000000")]})
    assert t.columns==("CY2024Q1",)
    assert t.rows[0].cells[0].value==Decimal("119580.00")
    li2=LineItem("revenue",("us-gaap:Revenues",),"USD","millions")
    t2=build_table(plan((li2,)), {A:[]})
    assert t2.rows[0].cells[0].value is None and "N/A" in t2.rows[0].cells[0].note
```

- [ ] **Step 2: Verify fail, implement `table.py`** (raw rows and the gross-margin derived branch in one `build_table`)
```python
from dataclasses import dataclass
from decimal import Decimal
from finagent.datasource.taxonomy import pick_concept
from finagent.datasource.facts import single_quarters
from finagent.metrics import scale_value, ratio
@dataclass(frozen=True)
class Cell:
    frame:str; value:Decimal|None; fact_id:str|None; note:str=""
@dataclass(frozen=True)
class TableRow:
    company:str; alias:str; scaling:str; cells:tuple[Cell,...]; formula:str|None=None
@dataclass(frozen=True)
class Table:
    columns:tuple[str,...]; rows:tuple[TableRow,...]
def _frames(facts_by_company,n):
    fr=set()
    for fs in facts_by_company.values():
        fr |= {f.frame for f in single_quarters(fs) if f.frame and f.frame.startswith("CY")}
    return tuple(sorted(fr)[-n:])
def _fact_map(facts):
    # (concept, frame) -> single-quarter Fact
    return {(f.concept,f.frame): f for f in single_quarters(facts)}
def build_table(plan,facts_by_company):
    cols=_frames(facts_by_company,plan.periods.n)
    rows=[]
    for comp in plan.companies:
        facts=facts_by_company.get(comp,[])
        concepts={f.concept for f in facts}
        sq=_fact_map(facts)
        for li in plan.line_items:
            cells=[]
            if li.kind=="derived" and li.formula=="gross_profit/revenue":
                gpc=pick_concept("gross_profit",concepts); rvc=pick_concept("revenue",concepts)
                for frame in cols:
                    gp=sq.get((gpc,frame)) if gpc else None
                    rv=sq.get((rvc,frame)) if rvc else None
                    if gp is None or rv is None:
                        cells.append(Cell(frame,None,None,"N/A: inputs not reported"))
                    else:
                        d=ratio(gp,rv)  # stored as fraction; display as percent
                        cells.append(Cell(frame,(d.value*100).quantize(Decimal("0.000001")),
                                         d.fact_id, "derived:gross_profit/revenue"))
                rows.append(TableRow(comp.ticker,li.alias,li.scaling,tuple(cells),li.formula))
                continue
            concept=pick_concept(li.alias,concepts)
            for frame in cols:
                f=sq.get((concept,frame)) if concept else None
                if f is None:
                    cells.append(Cell(frame,None,None,"N/A: not reported"))
                else:
                    note="derived:YTD_DIFF" if f.provenance.raw_value=="derived:YTD_DIFF" else ""
                    cells.append(Cell(frame,scale_value(f.value,li.scaling),f.fact_id,note))
            rows.append(TableRow(comp.ticker,li.alias,li.scaling,tuple(cells)))
    return Table(cols,tuple(rows))
```
The derived branch requires the plan to also contain `gross_profit` and `revenue` raw items (the planner schema only emits `gross_margin` when both inputs are present). Verify with two tests:
```python
def test_gross_margin():
    gp=LineItem("gross_profit",("us-gaap:GrossProfit",),"USD","millions")
    rv=LineItem("revenue",("us-gaap:Revenues",),"USD","millions")
    gm=LineItem("gross_margin",("us-gaap:GrossProfit","us-gaap:Revenues"),"USD","millions",
                kind="derived",formula="gross_profit/revenue")
    pl=QueryPlan((A,),(gp,rv,gm),PeriodSpec("last_n_quarters",1),("table",))
    data={A:[fact("CY2024Q1","50000000000","us-gaap:GrossProfit"),
             fact("CY2024Q1","100000000000","us-gaap:Revenues")]}
    gmrow=[r for r in build_table(pl,data).rows if r.alias=="gross_margin"][0]
    assert gmrow.cells[0].value==Decimal("50.000000") and gmrow.formula
```

- [ ] **Step 3: Implement `loop.py`**
```python
import json
from finagent.models import Company, LineItem, PeriodSpec, QueryPlan
SYSTEM = ("You plan SEC data retrieval. You never output numbers. "
          "Call a tool or return final JSON. Resolve ambiguity by asking.")
class AgentLoop:
    def __init__(self,llm,tools,max_turns=6):
        self.llm=llm; self.tools=tools; self.max_turns=max_turns
    def _parse_plan(self,d):
        comps=tuple(Company(c["ticker"],int(c["cik"]),c.get("name",c["ticker"]))
                    for c in d["companies"])
        items=tuple(LineItem(i["alias"],tuple(i["concepts"]),i["unit"],i["scaling"],
                             i.get("kind","raw"),i.get("formula")) for i in d["line_items"])
        return QueryPlan(comps,items,PeriodSpec(d["periods"]["type"],int(d["periods"]["n"])),
                         tuple(d["outputs"]))
    def run(self,question,profile_summary,known):
        msgs=[{"role":"user","content":f"{question}\n\nProfile: {profile_summary}"}]
        for _ in range(self.max_turns):
            out=self.llm.complete_json(SYSTEM,msgs,{"type":"object"})
            if "final" in out:
                plan=self._parse_plan(out["final"])
                from finagent.agent.planner import validate_plan
                errs=validate_plan(plan,known)
                if not errs: return plan
                msgs.append({"role":"assistant","content":json.dumps(out)})
                msgs.append({"role":"user","content":f"Plan rejected: {errs}"})
            else:
                res=self.tools.call(out["tool"],out.get("args",{}))
                msgs.append({"role":"assistant","content":json.dumps(out)})
                msgs.append({"role":"tool","content":json.dumps(res,ensure_ascii=False)})
        raise RuntimeError("planner did not converge")
```

- [ ] **Step 4: Failing loop test with a scripted fake LLM**
```python
from finagent.agent.loop import AgentLoop
from finagent.agent.tools import DataTools
from finagent.datasource.tickers import TickerResolver
from finagent.models import Company
class FakeSEC:  # same as Task 12
    def get_ticker_index(self): return [{"ticker":"AAPL","cik":320193,"title":"Apple Inc."}]
    def get_company_facts(self,cik):
        return {"cik":320193,"ticker":"AAPL","entityName":"Apple","facts":{"us-gaap":{
          "Revenues":{"units":{"USD":[{"val":1,"start":"2024-01-01","end":"2024-03-31",
          "form":"10-Q","filed":"2024-05-01","acc":"a","frame":"CY2024Q1"}]}}}}}
class ScriptedLLM:
    def __init__(self,outs): self.outs=outs; self.i=0
    def complete_json(self,*a,**k):
        o=self.outs[self.i]; self.i+=1; return o
def test_loop_converges():
    sec=FakeSEC(); dt=DataTools(sec,TickerResolver(sec))
    llm=ScriptedLLM([
      {"tool":"resolve_ticker","args":{"ticker":"AAPL"}},
      {"final":{"companies":[{"ticker":"AAPL","cik":320193,"name":"Apple"}],
        "line_items":[{"alias":"revenue",
          "concepts":["us-gaap:Revenues"],"unit":"USD","scaling":"millions"}],
        "periods":{"type":"last_n_quarters","n":1},"outputs":["table"]}}])
    known={Company("AAPL",320193,"Apple"):{"concepts":{"us-gaap:Revenues"}},
           "frames":{"CY2024Q1"}}
    p=AgentLoop(llm,dt).run("AAPL revenue","{}",known)
    assert p.companies[0].cik==320193
```
Add `tests/output/__init__.py`.

- [ ] **Step 5: Verify all pass, commit**
```bash
git add finagent/agent/loop.py finagent/output tests/agent/test_loop.py tests/output && git commit -m "feat: react loop and quarter-aligned table builder"
```

---

## Task 14: Summarizer and three-gate verifier

**Files:**
- Create: `finagent/narrative/__init__.py`, `finagent/narrative/summarizer.py`, `finagent/narrative/verifier.py`; Test: `tests/narrative/test_verifier.py`

**Interfaces:**
- Produces:
```python
@dataclass Verdict: claim_id:str; ok:bool; reason:str
def verify_claims(claims:list[Claim], index:dict[str, Fact|DerivedFact],
                  judge:Callable[[Claim],str], allowed_companies:set[str],
                  forbidden_companies:set[str], allowed_frames:set[str]) -> list[Verdict]
   # Gate1 every number token must match a bound evidence display string
   # Gate2 judge returns "supported"/"contradicted"/"not_grounded"
   # Gate3 any forbidden company token, or named ticker not in allowed set -> reject
def render_claim_text(c:Claim) -> str   # prefixes interpretation marker
```
Number extraction regex: `r"-?\d[\d,]*(?:\.\d+)?%?"`. Evidence entries carry an exact `display` string produced by `build_evidence_bundle` (e.g. `"5.4%"`, `"119580.00"`); Gate 1 requires every number token in a datapoint claim to equal (normalized) one of its bound evidence display strings. Strict and deterministic.

- [ ] **Step 1: Failing test**
```python
from finagent.narrative.verifier import verify_claims, render_claim_text
from finagent.models import Claim
def judge_supported(c): return "supported"
idx={"f1":type("E",(),{"display":"5.4%","company":"AAPL","frame":"CY2024Q1"})()}
ARGS = dict(index=idx, judge=judge_supported, allowed_companies={"AAPL"},
            forbidden_companies={"MSFT","GOOG","NVDA"}, allowed_frames={"CY2024Q1"})
def test_bare_number_rejected():
    v=verify_claims([Claim("c1","Revenue grew 5.4% to 999.",("f1",),"datapoint")], **ARGS)
    assert v[0].ok is False and "999" in v[0].reason
def test_good_claim_passes():
    v=verify_claims([Claim("c1","AAPL revenue grew 5.4%.",("f1",),"datapoint")], **ARGS)
    assert v[0].ok
def test_interpretation_marker():
    assert "模型解读" in render_claim_text(Claim("c","Solid.",(),"interpretation"))
def test_scope_violation():
    v=verify_claims([Claim("c","MSFT grew 5.4%.",("f1",),"datapoint")], **ARGS)
    assert v[0].ok is False
```

- [ ] **Step 2: Verify fail, implement `verifier.py`**
```python
import re
from dataclasses import dataclass
NUM=re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")
TICKER=re.compile(r"\b[A-Z]{2,5}\b")
INTERP_MARKER="【模型解读，非数据】"
@dataclass(frozen=True)
class Verdict:
    claim_id:str; ok:bool; reason:str
def _norm(t): return t.replace(",","").lstrip("0") or "0"
def render_claim_text(c):
    return f"{INTERP_MARKER} {c.text}" if c.claim_type=="interpretation" else c.text
def verify_claims(claims,index,judge,allowed_companies,forbidden_companies,allowed_frames):
    out=[]
    for c in claims:
        if c.claim_type=="interpretation":
            out.append(Verdict(c.id,True,"interpretation")); continue
        if not c.evidence_ids:
            out.append(Verdict(c.id,False,"datapoint without evidence")); continue
        allowed=set()
        missing=False
        for eid in c.evidence_ids:
            e=index.get(eid)
            if e is None:
                out.append(Verdict(c.id,False,f"missing evidence {eid}")); missing=True; break
            allowed.add(_norm(e.display))
        if missing: continue
        bad=[n for n in NUM.findall(c.text) if _norm(n) not in allowed]
        if bad:
            out.append(Verdict(c.id,False,f"unsupported numbers {bad}")); continue
        tokens=set(TICKER.findall(c.text))
        if tokens & forbidden_companies or (tokens and not (tokens & allowed_companies)):
            out.append(Verdict(c.id,False,"out-of-scope company")); continue
        verdict=judge(c)
        if verdict!="supported":
            out.append(Verdict(c.id,False,f"judge:{verdict}")); continue
        out.append(Verdict(c.id,True,"ok"))
    return out
```

`summarizer.py`:
```python
from finagent.models import Claim
def build_evidence_bundle(facts, derived):
    items=[]; index={}
    for f in facts:
        disp=f"{f.value} {f.unit}"
        items.append({"fact_id":f.fact_id,"label":f"{f.ticker} {f.frame or f.period_end} {f.concept}",
                      "display":disp,"company":f.ticker,"frame":f.frame})
        index[f.fact_id]=type("E",(),{"display":disp,"company":f.ticker,"frame":f.frame})()
    for d in derived:
        disp=f"{(d.value*100):.1f}%" if d.formula in ("ratio","yoy") else str(d.value)
        items.append({"fact_id":d.fact_id,"label":d.formula,"display":disp})
        index[d.fact_id]=type("E",(),{"display":disp})()
    return {"items":items}, index
SUMMARIZER_SYSTEM=("You write claims strictly from the evidence bundle. Every sentence with a "
  "number is claim_type datapoint and must cite evidence ids whose display string contains that "
  "exact number. Qualitative sentences are interpretation with empty evidence. No other companies "
  "or periods.")
def parse_claims(data):
    return [Claim(c["id"],c["text"],tuple(c["evidence_ids"]),c["claim_type"])
            for c in data["claims"]]
```
Add `tests/narrative/__init__.py`.

- [ ] **Step 3: Verify pass, then add rewrite-loop test** in app layer Task 15 (max 2 attempts then downgrade). Commit
```bash
git add finagent/narrative tests/narrative && git commit -m "feat: evidence-bound claims and three-gate verifier"
```

---

## Task 15: End-to-end app orchestration and CLI rendering

**Files:**
- Create: `finagent/app.py`, `finagent/output/cli.py`; Test: `tests/test_app.py`

**Interfaces:**
- Produces:
```python
@dataclass Result: plan:QueryPlan; table:Table; claims:list[Claim]; verdicts:list[Verdict];
                    facts_by_company:dict; index:dict
def run_query(question, cfg, llm, sec, profile_store, output_dir) -> Result
   # load profile -> resolver/tools -> gather known {Company:{"concepts"}, "frames"}
   # -> AgentLoop.run -> fetch facts_by_company (single_quarters) -> build_table
   # -> bundle -> summarizer (LLM, max 2 rewrites with verdict feedback) -> verify -> Result
def render_console(result) -> str
def main()  # argparse: --question, --profile NAME, --xlsx, --verbose; builds real clients
```
Rewrite loop: call LLM for claims; verify; if failures, append feedback message listing `(claim_id, reason)` and ask for corrected JSON; after 2 failures, drop failed datapoint claims from output and set a `downgraded` count (never silently emit). Interpretation claims always retained with marker.

- [ ] **Step 1: Failing orchestration test (scripted LLM, fake SEC, temp profile)**
```python
import json, pathlib
from finagent.app import run_query
from finagent.profile.store import ProfileStore
from finagent.datasource.tickers import TickerResolver
from finagent.cache import ResponseCache
from finagent.datasource.sec_client import SECClient
# (Use FakeSEC implementing get_ticker_index/get_company_facts; SECClient not needed if tools
#  accept the fake directly. Build DataTools(FakeSEC(), TickerResolver(FakeSEC())).)
# Scripted LLM returns: resolve tool result, final plan, claims JSON (all numbers match displays).
# Assert: table has one row, one datapoint claim verdict ok, downgraded==0.
```
Implement the test concretely using the FakeSEC/scripted LLM doubles from Tasks 12–14; assert a claim whose display value exists passes and a second run where first claims payload contains a bare number then a corrected payload exercises the rewrite path (downgraded stays 0, two LLM claim calls).

- [ ] **Step 2: Verify fail, implement `app.py`**
```python
from dataclasses import dataclass, field
from finagent.agent.tools import DataTools
from finagent.agent.loop import AgentLoop
from finagent.datasource.taxonomy import pick_concept
from finagent.datasource.facts import single_quarters
from finagent.output.table import build_table
from finagent.narrative.summarizer import build_evidence_bundle, parse_claims, SUMMARIZER_SYSTEM
from finagent.narrative.verifier import verify_claims
@dataclass
class Result:
    plan:object; table:object; claims:list; verdicts:list
    facts_by_company:dict; index:dict; downgraded:int=0
def run_query(question, llm, sec, resolver, profile, max_rewrites=2):
    tools=DataTools(sec,resolver)
    known={}; facts_by={}
    # company set discovered after planner resolves; do a priming pass:
    # run planner, then load facts for its resolved companies
    loop=AgentLoop(llm,tools)
    # planner needs known; seed with watchlist concepts/frames then expand:
    plan=_plan_with_priming(loop,llm,tools,question,profile)
    for comp in plan.companies:
        facts_by[comp]=single_quarters(tools._facts_for(comp.cik))
        known[comp]={"concepts":{f.concept for f in tools._facts_for(comp.cik)}}
    table=build_table(plan,facts_by)
    allfacts=[f for fs in facts_by.values() for f in fs]
    bundle,index=build_evidence_bundle(allfacts,[])
    msgs=[{"role":"user","content":json.dumps({"question":question,"evidence":bundle},ensure_ascii=False)}]
    claims=[]; verdicts=[]; downgraded=0
    for attempt in range(max_rewrites+1):
        data=llm.complete_json(SUMMARIZER_SYSTEM,msgs,{"type":"object"})
        claims=parse_claims(data)
        scope={c.ticker for c in plan.companies}
        verdicts=verify_claims(claims,index,lambda c:_judge(llm,c,bundle),
                               allowed_companies=scope,
                               forbidden_companies={"MSFT","GOOG","NVDA"}-scope,
                               allowed_frames=set(table.columns))
        if all(v.ok for v in verdicts): break
        msgs.append({"role":"assistant","content":json.dumps(data,ensure_ascii=False)})
        msgs.append({"role":"user","content":"Fix or remove these: "+
                     json.dumps([{"id":v.claim_id,"reason":v.reason} for v in verdicts if not v.ok])})
    bad={v.claim_id for v in verdicts if not v.ok}
    if bad:
        claims=[c for c in claims if c.id not in bad or c.claim_type=="interpretation"]
        downgraded=len(bad)
    return Result(plan,table,claims,verdicts,facts_by,index,downgraded)
def _judge(llm,claim,bundle):
    out=llm.complete_json("Judge supported/contradicted/not_grounded from evidence only.",
        [{"role":"user","content":json.dumps({"claim":claim.text,"evidence":bundle})}],
        {"type":"object"})
    return out.get("verdict","not_grounded")
def _plan_with_priming(loop,llm,tools,question,profile):
    # Drive the loop; after first resolve calls we know companies, so build known lazily.
    # Simplest correct approach used here: run loop with a known-provider that computes on demand.
    raise NotImplementedError  # implemented below
```
Implement `_plan_with_priming` by giving `AgentLoop.run` an optional `known_provider: callable(plan)->known` instead of a static dict; update `loop.run` signature to accept `known=None, known_provider=None` and validate using the provider's result right before finalizing. (Adjust Task 13 loop test to keep passing via the static `known` path.) Then:
```python
def _plan_with_priming(loop,llm,tools,question,profile):
    def provider(plan):
        known={"frames":set()}
        for comp in plan.companies:
            fs=tools._facts_for(comp.cik)
            known[comp]={"concepts":{f.concept for f in fs}}
            known["frames"] |= {f.frame for f in single_quarters(fs) if f.frame}
        return known
    summ={ "watchlist":[c.ticker for c in profile.watchlist],
           "aliases":profile.metric_aliases,"quarters":profile.default_quarters}
    return loop.run(question,json.dumps(summ,ensure_ascii=False),None,known_provider=provider)
```
`cli.py` renders the table with `rich.table.Table`, citation markers, N/A notes, interpretation marker (via `render_claim_text`), and a footer `【核查】X passed · N downgraded`.

- [ ] **Step 3: `main()` argparse wiring** — real `openai.OpenAI(api_key=...)`, `ResponseCache`, `SECClient(ua,cache)`, `TickerResolver`, `ProfileStore(cfg.profile_path)`; `--xlsx` delegates to Task 16 exporter; print console output.

- [ ] **Step 4: Verify pass, commit**
```bash
git add finagent/app.py finagent/output/cli.py tests/test_app.py && git commit -m "feat: end-to-end orchestration with claim rewrite loop and cli"
```

---

## Task 16: xlsx export with three sheets

**Files:**
- Create: `finagent/output/xlsx.py`; Test: `tests/output/test_xlsx.py`

**Interfaces:**
- Produces: `def export_xlsx(result:Result, path:pathlib.Path) -> pathlib.Path`. Sheets: `Comparison` (hyperlinked numeric cells + comments), `Provenance` (one row per distinct fact), `Claims` (id/text/type/evidence/verdict/reason). Uses openpyxl.

- [ ] **Step 1: Failing test**
```python
from finagent.output.xlsx import export_xlsx
def test_workbook_sheets(tmp_path):
    # build a minimal Result-like with one Fact table cell and one claim/verdict
    p=export_xlsx(fake_result(tmp_path), tmp_path/"out.xlsx")
    from openpyxl import load_workbook
    wb=load_workbook(p)
    assert set(wb.sheetnames)=={"Comparison","Provenance","Claims"}
    ws=wb["Provenance"]; assert ws.max_row>=2  # header + 1 fact
```
Provide a `fake_result` helper constructing a real `Fact`, a `Table` with one linked `Cell`, and one `Verdict`.

- [ ] **Step 2: Verify fail, implement `xlsx.py`**
```python
import pathlib
from openpyxl import Workbook
from openpyxl.comments import Comment
def export_xlsx(result,path):
    path=pathlib.Path(path); wb=Workbook()
    cmp=wb.active; cmp.title="Comparison"
    cmp.append(["Company / Metric",*result.table.columns])
    fact_index={}
    for fs in result.facts_by_company.values():
        for f in fs: fact_index[f.fact_id]=f
    for row in result.table.rows:
        cmp.append([f"{row.company} {row.alias}"]+[
            (c.value if c.value is not None else c.note) for c in row.cells])
        r=cmp.max_row
        for i,c in enumerate(row.cells,start=2):
            if c.fact_id and c.fact_id in fact_index:
                f=fact_index[c.fact_id]
                cmp.cell(r,i).hyperlink=f.provenance.source_url
                cmp.cell(r,i).comment=Comment(
                    f"{f.concept}\n{f.provenance.accession}\nfiled {f.provenance.filed_date}\n"
                    f"{f.provenance.raw_value} {f.unit}","finagent")
    prov=wb.create_sheet("Provenance")
    prov.append(["fact_id","ticker","company","concept","period_start","period_end",
                 "frame","raw_value","value","unit","form","accession","filed_date","source_url"])
    for f in fact_index.values():
        prov.append([f.fact_id,f.ticker,f.company_name,f.concept,str(f.period_start),
            str(f.period_end),f.frame,f.provenance.raw_value,str(f.value),f.unit,
            f.provenance.form,f.provenance.accession,f.provenance.filed_date,
            f.provenance.source_url])
    cl=wb.create_sheet("Claims")
    cl.append(["claim_id","text","type","evidence_ids","verdict","reason"])
    reasons={v.claim_id:v for v in result.verdicts}
    for c in result.claims:
        v=reasons.get(c.id)
        cl.append([c.id,c.text,c.claim_type,",".join(c.evidence_ids),
                   "pass" if v and v.ok else "fail", v.reason if v else ""])
    wb.save(path); return path
```

- [ ] **Step 3: Verify pass, wire `--xlsx` in `app.main` to write timestamped file + snapshot JSON of facts (ids/values/provenance) under `output/snapshots/`. Commit**
```bash
git add finagent/output/xlsx.py tests/output/test_xlsx.py finagent/app.py && git commit -m "feat: xlsx export with provenance and claims sheets"
```

---

## Task 17: Golden-set evaluation harness and baselines

**Files:**
- Create: `finagent/eval/__init__.py`, `finagent/eval/golden.yaml`, `finagent/eval/run_eval.py`; Test: `tests/eval/test_metrics.py`

**Interfaces:**
- Produces scoring functions (pure, unit-tested) plus a runner:
```python
def numeric_accuracy(predicted:dict[tuple,str], golden:dict[tuple,str], tol=Decimal("0.01"))->float
def provenance_validity(cells:list, fact_index:dict)->float   # linked fact value == shown value
def hallucination_rate(verdicts:list[Verdict])->float
def score_run(result, golden_case)->dict
def run_eval(golden_path, run_harness:callable, run_baseline:callable, out_md:pathlib.Path)->dict
```
`golden.yaml` contains the 15 cases per spec §7 (3/3/4/3/2) with `expected_cells: {company|alias|frame: displayed}` and `expected_behavior`. Baselines: `bare` (single prompt, no tools) and `linked` (prompt includes SEC URLs). Runner emits a markdown comparison report.

- [ ] **Step 1: Seed `golden.yaml`** with 15 cases. Start file:
```yaml
- id: single_01
  category: single
  question: "What was AAPL revenue for calendar 2024Q1 in USD millions?"
  expected_behavior: answer
  expected_cells: {"AAPL|revenue|CY2024Q1": "119580.00"}
- id: adv_01
  category: adversarial
  question: "apple income"
  expected_behavior: clarify
# ... complete all 15 per spec categories before running eval
```
(Author all 15 with hand-verified values pulled from cached SEC data during integration; values for AAPL/MSFT/NVDA/GOOG are filled from the fixture/cache, never guessed.)

- [ ] **Step 2: Failing metric tests**
```python
from decimal import Decimal
from finagent.eval.run_eval import numeric_accuracy, hallucination_rate
from finagent.narrative.verifier import Verdict
def test_numeric():
    g={("A","revenue","CY2024Q1"):"119580.00"}
    assert numeric_accuracy({("A","revenue","CY2024Q1"):"119580.00"},g)==1.0
    assert numeric_accuracy({("A","revenue","CY2024Q1"):"999.00"},g)==0.0
def test_hall():
    vs=[Verdict("a",True,""),Verdict("b",False,"x")]
    assert hallucination_rate(vs)==0.5
```

- [ ] **Step 3: Verify fail, implement metrics in `run_eval.py`**
```python
from decimal import Decimal
def numeric_accuracy(pred,golden,tol=Decimal("0.01")):
    if not golden: return 0.0
    ok=0
    for k,v in golden.items():
        try:
            if abs(Decimal(pred.get(k,"0"))-Decimal(v))<=tol: ok+=1
        except Exception: pass
    return ok/len(golden)
def hallucination_rate(verdicts):
    if not verdicts: return 0.0
    return sum(0 if v.ok else 1 for v in verdicts)/len(verdicts)
def provenance_validity(cells,index):
    links=[c for c in cells if c.fact_id]
    if not cells: return 0.0
    good=sum(1 for c in links if c.fact_id in index)
    return good/len(cells)
```
Then implement `score_run` (compose the three + task completion + boundary behavior) and `run_eval` (loop cases, call both runners, write a markdown table comparing harness vs bare vs linked on each metric). The two baseline callers use `LLMClient.complete_json` with a plain system prompt and no tools; their free-form numbers are parsed and scored by the same functions (provenance_validity ~0 because they produce no fact links).

- [ ] **Step 4: Add README** (`README.md`) per submission: setup (`pip install -e '.[dev]'`, set `OPENAI_API_KEY`, SEC contact), usage (`finagent --question "..." --xlsx`), design summary (3 invariants), evaluation (`python -m finagent.eval.run_eval`) and how to read the report.

- [ ] **Step 5: Run full suite** `pytest -q` (all offline). Fix and commit**
```bash
git add finagent/eval README.md tests/eval && git commit -m "feat: golden-set evaluation, baselines, and README"
```

---

## Self-Review Notes (coverage vs spec)

- §2 architecture/lifecycle/invariants → Tasks 1, 11–15 (LLM excluded from numeric path).
- §3 Fact/Provenance, Decimal, immutability → Task 2; SEC client/UA/cache → 3–4; normalization/dedup/YTD/frames/N-A → 7–8; taxonomy → 6.
- §4 QueryPlan/tools/validation/ambiguity/profile → 10, 12, 13.
- §5 claims + 3 gates + rewrite/downgrade + table checks → 14, 15.
- §6 CLI/xlsx 3 sheets/snapshot → 15, 16.
- §7 golden set/metrics/baselines → 17.
- §8 errors: throttling/backoff in Task 4 client (raise_for_status; add bounded retry on 429/5xx during implementation), explicit clarification/downgrade in 13–15.
- §9 tests: every task TDD with offline fixtures; live SEC runs are a manual opt-in smoke test documented in the README.

Known simplification flagged for the executor: Task 8 YTD-diff provenance keeps the cumulative filing and marks `raw_value="derived:YTD_DIFF"`; Task 13/16 must surface this marker (comment/footnote) so a differenced cell is visibly not a directly reported number. Implement that footnote when wiring gross-margin/derived rows.
