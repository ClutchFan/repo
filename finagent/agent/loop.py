import json

from finagent.models import Company, LineItem, PeriodSpec, QueryPlan

SYSTEM = (
    "You plan SEC data retrieval. You never output numbers. "
    "Call a tool or return final JSON. Resolve ambiguity by asking."
)


class AgentLoop:
    def __init__(self, llm, tools, max_turns=6):
        self.llm = llm
        self.tools = tools
        self.max_turns = max_turns

    def _parse_plan(self, d):
        comps = tuple(
            Company(c["ticker"], int(c["cik"]), c.get("name", c["ticker"]))
            for c in d["companies"]
        )
        items = tuple(
            LineItem(
                i["alias"],
                tuple(i["concepts"]),
                i["unit"],
                i["scaling"],
                i.get("kind", "raw"),
                i.get("formula"),
            )
            for i in d["line_items"]
        )
        return QueryPlan(
            comps,
            items,
            PeriodSpec(d["periods"]["type"], int(d["periods"]["n"])),
            tuple(d["outputs"]),
        )

    def run(self, question, profile_summary, known=None, known_provider=None):
        from finagent.agent.planner import validate_plan

        msgs = [{"role": "user", "content": f"{question}\n\nProfile: {profile_summary}"}]
        for _ in range(self.max_turns):
            out = self.llm.complete_json(SYSTEM, msgs, {"type": "object"})
            if "final" in out:
                plan = self._parse_plan(out["final"])
                if known is not None:
                    errs = validate_plan(plan, known)
                elif known_provider is not None:
                    known_map = known_provider(plan)
                    errs = validate_plan(plan, known_map)
                else:
                    return plan
                if not errs:
                    return plan
                msgs.append({"role": "assistant", "content": json.dumps(out)})
                msgs.append({"role": "user", "content": f"Plan rejected: {errs}"})
            else:
                res = self.tools.call(out["tool"], out.get("args", {}))
                msgs.append({"role": "assistant", "content": json.dumps(out)})
                msgs.append({"role": "tool", "content": json.dumps(res, ensure_ascii=False)})
        raise RuntimeError("planner did not converge")
