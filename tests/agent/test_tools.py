from finagent.agent.tools import DataTools
from finagent.datasource.tickers import TickerResolver


class FakeSEC:
    def get_ticker_index(self):
        return [{"ticker": "AAPL", "cik": 320193, "title": "Apple Inc."}]

    def get_company_facts(self, cik):
        return {
            "cik": 320193,
            "ticker": "AAPL",
            "entityName": "Apple Inc.",
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
                                    "acc": "0000320193-24-000006",
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


def test_resolve_and_concepts():
    dt = DataTools(FakeSEC(), TickerResolver(FakeSEC()))
    r = dt.call("resolve_ticker", {"ticker": "AAPL"})
    assert r["ok"] and r["company"]["cik"] == 320193
    c = dt.call("list_concepts", {"cik": 320193, "query": "revenue"})
    assert any("Revenues" in x for x in c["concepts"])
    p = dt.call("list_available_periods", {"cik": 320193})
    assert "CY2024Q1" in p["frames"]


def test_unknown_tool_returns_error():
    dt = DataTools(FakeSEC(), TickerResolver(FakeSEC()))
    r = dt.call("nonexistent_tool", {})
    assert r["ok"] is False
    assert "unknown tool" in r["error"]


def test_bad_args_returns_error():
    dt = DataTools(FakeSEC(), TickerResolver(FakeSEC()))
    r = dt.call("resolve_ticker", {"bad_key": "AAPL"})
    assert r["ok"] is False
    assert "error" in r


def test_preview_metric():
    dt = DataTools(FakeSEC(), TickerResolver(FakeSEC()))
    r = dt.call("preview_metric", {"cik": 320193, "concept": "us-gaap:Revenues"})
    assert r["ok"] is True
    assert r["frame"] == "CY2024Q1"


def test_preview_metric_not_reported():
    dt = DataTools(FakeSEC(), TickerResolver(FakeSEC()))
    r = dt.call("preview_metric", {"cik": 320193, "concept": "us-gaap:Nope"})
    assert r["ok"] is False
    assert r["reason"] == "not reported"
