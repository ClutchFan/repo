"""Canonical offline fixture values for the evaluation golden set.

Every numeric cell in golden.yaml traces to a constant defined here.
These are fixture-contract values used for offline scoring only.
Before any published eval run, values must be re-verified against live SEC EDGAR data.

The four demo tickers: AAPL, MSFT, NVDA, GOOG.
Frames covered: CY2023Q1 through CY2024Q4 (8 quarters).
Metrics: revenue, gross_profit, net_income.

All raw values are in USD (the base unit SEC reports in).
Display values (millions) are produced by scale_value(value, "millions").
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from finagent.models import Fact, Provenance, make_fact_id
from finagent.metrics import scale_value

# ---------------------------------------------------------------------------
# Company metadata
# ---------------------------------------------------------------------------

COMPANIES = {
    "AAPL": {"cik": 320193, "name": "Apple Inc."},
    "MSFT": {"cik": 789019, "name": "Microsoft Corp."},
    "NVDA": {"cik": 1045810, "name": "NVIDIA Corp."},
    "GOOG": {"cik": 1652044, "name": "Alphabet Inc."},
}

# ---------------------------------------------------------------------------
# Raw SEC values (USD, full precision) — canonical source of truth
#
# Structure: RAW_VALUES[ticker][concept][frame] = Decimal(raw_usd)
# concept keys use the GAAP concept name (not alias).
# ---------------------------------------------------------------------------

RAW_VALUES: dict[str, dict[str, dict[str, Decimal]]] = {
    "AAPL": {
        "Revenues": {
            "CY2023Q1": Decimal("94836000000"),
            "CY2023Q2": Decimal("85777000000"),
            "CY2023Q3": Decimal("81797000000"),
            "CY2023Q4": Decimal("119575000000"),
            "CY2024Q1": Decimal("119580000000"),
            "CY2024Q2": Decimal("95076000000"),
            "CY2024Q3": Decimal("90146000000"),
            "CY2024Q4": Decimal("124292000000"),
        },
        "GrossProfit": {
            "CY2023Q1": Decimal("42318000000"),
            "CY2023Q2": Decimal("38245000000"),
            "CY2023Q3": Decimal("36448000000"),
            "CY2023Q4": Decimal("51972000000"),
            "CY2024Q1": Decimal("50000000000"),
            "CY2024Q2": Decimal("42243000000"),
            "CY2024Q3": Decimal("40285000000"),
            "CY2024Q4": Decimal("55628000000"),
        },
        "NetIncomeLoss": {
            "CY2023Q1": Decimal("24156000000"),
            "CY2023Q2": Decimal("22608000000"),
            "CY2023Q3": Decimal("14882000000"),
            "CY2023Q4": Decimal("33916000000"),
            "CY2024Q1": Decimal("26442000000"),
            "CY2024Q2": Decimal("24157000000"),
            "CY2024Q3": Decimal("22956000000"),
            "CY2024Q4": Decimal("36678000000"),
        },
    },
    "MSFT": {
        "Revenues": {
            "CY2023Q1": Decimal("52857000000"),
            "CY2023Q2": Decimal("56189000000"),
            "CY2023Q3": Decimal("56517000000"),
            "CY2023Q4": Decimal("62020000000"),
            "CY2024Q1": Decimal("61859000000"),
            "CY2024Q2": Decimal("64699000000"),
            "CY2024Q3": Decimal("66826000000"),
            "CY2024Q4": Decimal("71197000000"),
        },
        "GrossProfit": {
            "CY2023Q1": Decimal("35942000000"),
            "CY2023Q2": Decimal("38253000000"),
            "CY2023Q3": Decimal("38024000000"),
            "CY2023Q4": Decimal("41492000000"),
            "CY2024Q1": Decimal("42752000000"),
            "CY2024Q2": Decimal("44333000000"),
            "CY2024Q3": Decimal("46099000000"),
            "CY2024Q4": Decimal("49213000000"),
        },
        "NetIncomeLoss": {
            "CY2023Q1": Decimal("18299000000"),
            "CY2023Q2": Decimal("20081000000"),
            "CY2023Q3": Decimal("22286000000"),
            "CY2023Q4": Decimal("21867000000"),
            "CY2024Q1": Decimal("24265000000"),
            "CY2024Q2": Decimal("22586000000"),
            "CY2024Q3": Decimal("22425000000"),
            "CY2024Q4": Decimal("27254000000"),
        },
    },
    "NVDA": {
        "Revenues": {
            "CY2023Q1": Decimal("7192000000"),
            "CY2023Q2": Decimal("13507000000"),
            "CY2023Q3": Decimal("18120000000"),
            "CY2023Q4": Decimal("22103000000"),
            "CY2024Q1": Decimal("26044000000"),
            "CY2024Q2": Decimal("30040000000"),
            "CY2024Q3": Decimal("35023000000"),
            "CY2024Q4": Decimal("40223000000"),
        },
        "GrossProfit": {
            "CY2023Q1": Decimal("4626000000"),
            "CY2023Q2": Decimal("9123000000"),
            "CY2023Q3": Decimal("12556000000"),
            "CY2023Q4": Decimal("15448000000"),
            "CY2024Q1": Decimal("18487000000"),
            "CY2024Q2": Decimal("21428000000"),
            "CY2024Q3": Decimal("25122000000"),
            "CY2024Q4": Decimal("28961000000"),
        },
        "NetIncomeLoss": {
            "CY2023Q1": Decimal("2043000000"),
            "CY2023Q2": Decimal("6188000000"),
            "CY2023Q3": Decimal("9243000000"),
            "CY2023Q4": Decimal("12285000000"),
            "CY2024Q1": Decimal("14879000000"),
            "CY2024Q2": Decimal("17299000000"),
            "CY2024Q3": Decimal("20127000000"),
            "CY2024Q4": Decimal("23668000000"),
        },
    },
    "GOOG": {
        "Revenues": {
            "CY2023Q1": Decimal("69787000000"),
            "CY2023Q2": Decimal("74604000000"),
            "CY2023Q3": Decimal("76693000000"),
            "CY2023Q4": Decimal("86308000000"),
            "CY2024Q1": Decimal("80539000000"),
            "CY2024Q2": Decimal("84717000000"),
            "CY2024Q3": Decimal("89127000000"),
            "CY2024Q4": Decimal("97225000000"),
        },
        "GrossProfit": {
            "CY2023Q1": Decimal("41830000000"),
            "CY2023Q2": Decimal("45326000000"),
            "CY2023Q3": Decimal("46897000000"),
            "CY2023Q4": Decimal("53724000000"),
            "CY2024Q1": Decimal("49425000000"),
            "CY2024Q2": Decimal("52054000000"),
            "CY2024Q3": Decimal("54892000000"),
            "CY2024Q4": Decimal("59887000000"),
        },
        "NetIncomeLoss": {
            "CY2023Q1": Decimal("15051000000"),
            "CY2023Q2": Decimal("18368000000"),
            "CY2023Q3": Decimal("19687000000"),
            "CY2023Q4": Decimal("20687000000"),
            "CY2024Q1": Decimal("22562000000"),
            "CY2024Q2": Decimal("22616000000"),
            "CY2024Q3": Decimal("26302000000"),
            "CY2024Q4": Decimal("27872000000"),
        },
    },
}

# ---------------------------------------------------------------------------
# Concept aliases mapping (alias -> GAAP concept name)
# ---------------------------------------------------------------------------

ALIAS_TO_CONCEPT = {
    "revenue": "Revenues",
    "gross_profit": "GrossProfit",
    "net_income": "NetIncomeLoss",
}

# ---------------------------------------------------------------------------
# Helper: display value for a ticker/alias/frame triple (millions, 2dp)
# ---------------------------------------------------------------------------

def display_value(ticker: str, alias: str, frame: str) -> str:
    """Return the canonical display string for a golden cell (millions, 2dp)."""
    concept = ALIAS_TO_CONCEPT[alias]
    raw = RAW_VALUES[ticker][concept][frame]
    return str(scale_value(raw, "millions"))


# ---------------------------------------------------------------------------
# Build canonical Fact objects for a ticker across specified frames/concepts
# ---------------------------------------------------------------------------

def build_facts(
    ticker: str,
    aliases: list[str] | None = None,
    frames: list[str] | None = None,
) -> list[Fact]:
    """Build a list of Fact objects for the given ticker.

    Each fact has deterministic provenance (accession number derived from ticker/frame,
    filed_date two weeks after quarter end, form 10-Q for Q1-Q3, 10-K for Q4).

    If aliases is None, all three metrics are included.
    If frames is None, all 8 quarters (CY2023Q1-CY2024Q4) are included.
    """
    if aliases is None:
        aliases = list(ALIAS_TO_CONCEPT.keys())
    if frames is None:
        frames = [f"CY{y}Q{q}" for y in (2023, 2024) for q in (1, 2, 3, 4)]

    cik = COMPANIES[ticker]["cik"]
    name = COMPANIES[ticker]["name"]
    facts = []

    for alias in aliases:
        concept = ALIAS_TO_CONCEPT[alias]
        for frame in frames:
            if frame not in RAW_VALUES[ticker][concept]:
                continue
            raw_val = RAW_VALUES[ticker][concept][frame]

            # Quarter end date derived from frame
            year = int(frame[2:6])
            q = int(frame[7])
            end_month = {1: 3, 2: 6, 3: 9, 4: 12}[q]
            end_day = {1: 31, 2: 30, 3: 30, 4: 31}[q]
            period_end = date(year, end_month, end_day)
            # 91-day quarters (simplified: start = end - 90 days)
            from datetime import timedelta
            period_start = period_end - timedelta(days=90)

            form = "10-K" if q == 4 else "10-Q"
            # Filed ~2 weeks after quarter end
            filed_date = (period_end + timedelta(days=14)).isoformat()
            fp = f"Q{q}"
            fy = year

            # Accession number: cik-padded + year + q + seq
            acc = f"{cik:010d}-{str(year)[-2:]}-0000{q}1"

            src = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-','')}/{acc}-index.htm"
            viewer = f"https://www.sec.gov/cgi-bin/viewer?action=view&cik={cik}&accession_number={acc}"

            prov = Provenance(
                accession=acc,
                form=form,
                filed_date=filed_date,
                fiscal_period=fp,
                fiscal_year=fy,
                concept=f"us-gaap:{concept}",
                source_url=src,
                xbrl_fact_url=viewer,
                raw_value=str(raw_val),
            )

            fid = make_fact_id(ticker, f"us-gaap:{concept}", "USD",
                               str(period_start), str(period_end), acc, str(raw_val))

            facts.append(Fact(
                fact_id=fid,
                cik=cik,
                ticker=ticker,
                company_name=name,
                value=raw_val,
                unit="USD",
                concept=f"us-gaap:{concept}",
                period_start=period_start,
                period_end=period_end,
                frame=frame,
                provenance=prov,
            ))

    return facts


# ---------------------------------------------------------------------------
# Build FakeSEC-compatible companyfacts dict for a ticker
# ---------------------------------------------------------------------------

def build_companyfacts(ticker: str, aliases: list[str] | None = None,
                       frames: list[str] | None = None) -> dict:
    """Build a companyfacts-style dict (SECClient.get_company_facts shape)
    for the given ticker using the fixture values."""
    if aliases is None:
        aliases = list(ALIAS_TO_CONCEPT.keys())
    if frames is None:
        frames = [f"CY{y}Q{q}" for y in (2023, 2024) for q in (1, 2, 3, 4)]

    cik = COMPANIES[ticker]["cik"]
    name = COMPANIES[ticker]["name"]

    facts_by_concept: dict[str, list[dict]] = {}
    for alias in aliases:
        concept = ALIAS_TO_CONCEPT[alias]
        entries = []
        for frame in frames:
            if frame not in RAW_VALUES[ticker][concept]:
                continue
            raw_val = RAW_VALUES[ticker][concept][frame]

            year = int(frame[2:6])
            q = int(frame[7])
            end_month = {1: 3, 2: 6, 3: 9, 4: 12}[q]
            end_day = {1: 31, 2: 30, 3: 30, 4: 31}[q]
            from datetime import date, timedelta
            period_end = date(year, end_month, end_day)
            period_start = period_end - timedelta(days=90)

            form = "10-K" if q == 4 else "10-Q"
            filed_date = (period_end + timedelta(days=14)).isoformat()
            acc = f"{cik:010d}-{str(year)[-2:]}-0000{q}1"

            entries.append({
                "val": str(raw_val),
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
                "form": form,
                "filed": filed_date,
                "acc": acc,
                "frame": frame,
                "fy": year,
                "fp": f"Q{q}",
            })
        facts_by_concept[concept] = {"units": {"USD": entries}}

    return {
        "cik": cik,
        "ticker": ticker,
        "entityName": name,
        "facts": {"us-gaap": facts_by_concept},
    }
