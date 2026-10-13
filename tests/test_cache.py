from finagent.cache import ResponseCache

def test_roundtrip(tmp_path):
    c = ResponseCache(tmp_path / "c.sqlite")
    assert c.get("http://x") is None
    c.set("http://x", "{}")
    assert c.get("http://x") == "{}"
