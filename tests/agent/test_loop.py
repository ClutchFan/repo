from finagent.agent.loop import AgentLoop
from finagent.agent.tools import DataTools
from finagent.datasource.tickers import TickerResolver
from finagent.models import Company


class FakeSEC:
    def get_ticker_index(self):
        return [{"ticker": "AAPL", "cik": 320193, "title": "Apple Inc."}]

    def get_company_facts(self, cik):
        return {
            "cik": 320193,
            "ticker": "AAPL",
            "entityName": "Apple",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "val": 1,
                                    "start": "2024-01-01",
                                    "end": "2024-03-31",
                                    "form": "10-Q",
                                    "filed": "2024-05-01",
                                    "acc": "a",
                                    "frame": "CY2024Q1",
                                    "fy": 2024,
                                    "fp": "Q1",
                                }
                            ]
                        }
                    }
                }
            },
        }


class ScriptedLLM:
    def __init__(self, outs):
        self.outs = outs
        self.i = 0

    def complete_json(self, *a, **k):
        o = self.outs[self.i]
        self.i += 1
        return o


def test_loop_converges():
    sec = FakeSEC()
    dt = DataTools(sec, TickerResolver(sec))
    llm = ScriptedLLM(
        [
            {"tool": "resolve_ticker", "args": {"ticker": "AAPL"}},
            {
                "final": {
                    "companies": [{"ticker": "AAPL", "cik": 320193, "name": "Apple"}],
                    "line_items": [
                        {
                            "alias": "revenue",
                            "concepts": ["us-gaap:Revenues"],
                            "unit": "USD",
                            "scaling": "millions",
                        }
                    ],
                    "periods": {"type": "last_n_quarters", "n": 1},
                    "outputs": ["table"],
                }
            },
        ]
    )
    known = {
        Company("AAPL", 320193, "Apple"): {"concepts": {"us-gaap:Revenues"}},
        "frames": {"CY2024Q1"},
    }
    p = AgentLoop(llm, dt).run("AAPL revenue", "{}", known)
    assert p.companies[0].cik == 320193
