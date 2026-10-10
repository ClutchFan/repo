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

def test_substring_name_returns_candidate():
    r = TickerResolver(FakeSEC())
    result = r.resolve("apple")
    assert result == Company("AAPL", 320193, "Apple Inc.")

def test_ambiguous_ticker_raises():
    # Test with a string that would match multiple candidates
    class FakeSECWithMore:
        def get_ticker_index(self):
            return [
                {"ticker":"AAPL","cik":320193,"title":"Apple Inc."},
                {"ticker":"MSFT","cik":789019,"title":"Microsoft Corp."},
                {"ticker":"GOOGL","cik":1340090,"title":"Apple Hospitality REIT Inc."}
            ]
    r = TickerResolver(FakeSECWithMore())
    with pytest.raises(AmbiguousTicker) as e:
        r.resolve("apple")
    assert len(e.value.candidates) >= 2
