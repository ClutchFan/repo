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
