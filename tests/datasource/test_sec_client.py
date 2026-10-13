import httpx
import pytest
from finagent.cache import ResponseCache
from finagent.datasource.sec_client import SECClient

def test_get_json_caches_and_headers(httpx_mock, tmp_path):
    httpx_mock.add_response(url="https://data.sec.gov/x.json", json={"ok": True})
    cache = ResponseCache(tmp_path / "c.sqlite")
    c = SECClient("Jane jane@example.com", cache, min_interval=0)

    # First call - should make actual HTTP request
    assert c.get_json("/x.json") == {"ok": True}

    # Second call - should be served from cache (no new request)
    assert c.get_json("/x.json") == {"ok": True}

    # Verify only one actual HTTP request was made
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    # Verify User-Agent header contains the contact email
    assert "jane@example.com" in requests[0].headers["user-agent"]
