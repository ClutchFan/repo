"""End-to-end orchestration for the financial research agent.

Run a natural-language question through the full pipeline:
  planner (AgentLoop with known_provider priming)
  -> fact gathering -> table build
  -> evidence bundle -> summarizer LLM (with rewrite loop)
  -> verification -> Result

CLI entry point: `python -m finagent.app --question "..." [--profile PATH] [--xlsx PATH] [--verbose]`
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime

from finagent.agent.tools import DataTools
from finagent.agent.loop import AgentLoop
from finagent.agent.llm import PLAN_SCHEMA, CLAIMS_SCHEMA, VERDICT_SCHEMA
from finagent.datasource.facts import quarter_facts
from finagent.output.table import build_table
from finagent.narrative.summarizer import (
    build_evidence_bundle,
    parse_claims,
    SUMMARIZER_SYSTEM,
)
from finagent.narrative.verifier import verify_claims

# The four demo tickers the harness covers.
COVERED_TICKERS = ("AAPL", "MSFT", "NVDA", "GOOG")


@dataclass
class Result:
    """Full pipeline result. Field order is load-bearing (Task 16/17)."""
    plan: object
    table: object
    claims: list
    verdicts: list
    facts_by_company: dict
    index: dict
    downgraded: int = 0


def run_query(question, llm, sec, resolver, profile, judge=None, max_rewrites=2):
    """Run the full query pipeline and return a Result.

    Args:
        question: the user's natural-language question
        llm: LLMClient-compatible object (complete_json method)
        sec: SEC client (get_ticker_index, get_company_facts)
        resolver: TickerResolver
        profile: Profile object
        judge: callable(claim) -> "supported"/"contradicted"/"not_grounded".
               If None, a default LLM-based judge is used.
        max_rewrites: max extra summarizer calls after first failure (default 2)

    Returns:
        Result dataclass
    """
    tools = DataTools(sec, resolver)

    # --- Phase 1: Plan with priming (known_provider discovers facts on demand) ---
    plan = _plan_with_priming(llm, tools, question, profile)

    # --- Phase 2: Gather raw facts & build table ---
    facts_by_company = {}
    for comp in plan.companies:
        facts_by_company[comp] = tools._facts_for(comp.cik)

    table = build_table(plan, facts_by_company)

    # --- Phase 3: Build evidence bundle (flatten quarter_facts per company) ---
    all_facts = []
    for comp_facts in facts_by_company.values():
        all_facts.extend(quarter_facts(comp_facts))

    bundle, index = build_evidence_bundle(all_facts, [])

    # --- Phase 4: Summarizer + verify + rewrite loop ---
    msgs = [{
        "role": "user",
        "content": json.dumps(
            {"question": question, "evidence": bundle},
            ensure_ascii=False,
        ),
    }]

    scope = {c.ticker for c in plan.companies}
    forbidden = set(COVERED_TICKERS) - scope

    claims = []
    verdicts = []
    downgraded = 0

    if judge is None:
        judge = lambda c: _judge_with_llm(llm, c, bundle)

    for attempt in range(max_rewrites + 1):
        data = llm.complete_json(SUMMARIZER_SYSTEM, msgs, CLAIMS_SCHEMA)
        claims = parse_claims(data)
        verdicts = verify_claims(
            claims,
            index,
            judge,
            allowed_companies=scope,
            forbidden_companies=forbidden,
            allowed_frames=set(table.columns),
        )
        if all(v.ok for v in verdicts):
            break
        # Append the failed response + feedback for the next attempt
        msgs.append({
            "role": "assistant",
            "content": json.dumps(data, ensure_ascii=False),
        })
        failed = [
            {"id": v.claim_id, "reason": v.reason}
            for v in verdicts if not v.ok
        ]
        msgs.append({
            "role": "user",
            "content": "Fix or remove these: " + json.dumps(failed, ensure_ascii=False),
        })

    # --- Phase 5: Drop failed datapoint claims, keep interpretations ---
    bad_ids = {v.claim_id for v in verdicts if not v.ok}
    if bad_ids:
        # Drop only failed claims that are NOT interpretations.
        # Interpretations are always retained even if somehow in bad_ids.
        dropped = {c.id for c in claims if c.id in bad_ids and c.claim_type != "interpretation"}
        claims = [c for c in claims if c.id not in dropped]
        downgraded = len(dropped)

    return Result(plan, table, claims, verdicts, facts_by_company, index, downgraded)


def _plan_with_priming(llm, tools, question, profile):
    """Run AgentLoop with a known_provider that lazily loads facts per company.

    The planner first resolves tickers / browses concepts; when it emits a final
    plan, known_provider(plan) is called — it fetches company facts for every
    company in the plan, builds the known map (concepts per company + frames),
    and validate_plan checks feasibility. If validation fails, the planner gets
    the error list and tries again.
    """
    def known_provider(plan):
        known = {"frames": set()}
        for comp in plan.companies:
            raw = tools._facts_for(comp.cik)
            known[comp] = {"concepts": {f.concept for f in raw}}
            qf = quarter_facts(raw)
            known["frames"] |= {f.frame for f in qf if f.frame}
        return known

    summ = {
        "watchlist": [c.ticker for c in profile.watchlist],
        "aliases": profile.metric_aliases,
        "quarters": profile.default_quarters,
    }
    profile_summary = json.dumps(summ, ensure_ascii=False)

    loop = AgentLoop(llm, tools)
    return loop.run(question, profile_summary, None, known_provider=known_provider)


def _judge_with_llm(llm, claim, bundle):
    """Default judge: ask the LLM whether the claim is supported by evidence."""
    JUDGE_SYSTEM = (
        "Judge whether the claim is supported, contradicted, or not_grounded "
        "from the evidence bundle only. Respond with {\"verdict\": ...}."
    )
    out = llm.complete_json(
        JUDGE_SYSTEM,
        [{
            "role": "user",
            "content": json.dumps(
                {"claim": claim.text, "evidence": bundle},
                ensure_ascii=False,
            ),
        }],
        VERDICT_SCHEMA,
    )
    return out.get("verdict", "not_grounded")


def main():
    """CLI entry point. Builds real clients and runs the full pipeline."""
    parser = argparse.ArgumentParser(description="Financial research agent — SEC EDGAR XBRL queries")
    parser.add_argument("--question", required=True, help="Natural-language question")
    parser.add_argument(
        "--profile",
        default=None,
        help="Path to profile JSON (default: cfg.profile_path)",
    )
    parser.add_argument(
        "--xlsx",
        nargs="?",
        const="auto",
        default=None,
        metavar="PATH",
        help="Export result to XLSX. Without PATH: output/finagent-YYYYMMDD-HHMMSS.xlsx",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Build config from environment
    from finagent.config import Config
    from finagent.cache import ResponseCache
    from finagent.datasource.sec_client import SECClient
    from finagent.datasource.tickers import TickerResolver
    from finagent.agent.llm import LLMClient
    from finagent.profile.store import ProfileStore
    from finagent.output.cli import render_console

    sec_name = os.environ.get("SEC_NAME", "")
    sec_email = os.environ.get("SEC_EMAIL", "")
    sec_contact = (sec_name, sec_email) if sec_name and sec_email else None
    if sec_contact is None:
        print("Error: SEC_NAME and SEC_EMAIL environment variables are required.", file=sys.stderr)
        sys.exit(1)

    cfg = Config.from_env(os.environ, sec_contact=sec_contact)

    if not cfg.openai_api_key:
        print("Error: OPENAI_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)

    # Build real clients
    import openai
    oai_client = openai.OpenAI(api_key=cfg.openai_api_key)
    llm = LLMClient(oai_client, cfg.model)

    cache = ResponseCache(cfg.cache_path)
    sec = SECClient(cfg.sec_user_agent, cache)
    resolver = TickerResolver(sec)

    profile_path = args.profile or cfg.profile_path
    profile_store = ProfileStore(profile_path)
    profile = profile_store.load()

    if args.verbose:
        print(f"Profile loaded from {profile_path}")
        print(f"Watchlist: {[c.ticker for c in profile.watchlist]}")

    # Run the query
    result = run_query(args.question, llm, sec, resolver, profile)

    # Render to console
    print(render_console(result))

    # XLSX export (lazy import — Task 16 module may not exist yet)
    if args.xlsx:
        try:
            from finagent.output.xlsx import export_xlsx
        except ImportError:
            print(
                "Error: finagent.output.xlsx is not available (Task 16 not installed). "
                "Cannot export to XLSX.",
                file=sys.stderr,
            )
            sys.exit(1)
        if args.xlsx == "auto":
            import pathlib
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            out_dir = pathlib.Path("output")
            out_dir.mkdir(parents=True, exist_ok=True)
            xlsx_path = out_dir / f"finagent-{ts}.xlsx"
        else:
            xlsx_path = args.xlsx
        export_xlsx(result, xlsx_path)
        if args.verbose:
            print(f"XLSX exported to {xlsx_path}")


if __name__ == "__main__":
    main()
