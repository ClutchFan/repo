from finagent.profile.store import ProfileStore, ProfileUpdate
from finagent.models import Company


def test_defaults_and_update(tmp_path):
    s = ProfileStore(tmp_path / "p.json")
    p = s.load()
    assert p.default_quarters == 4 and p.watchlist == []
    p = s.apply_update(ProfileUpdate(
        add_watchlist=[Company("NVDA", 1045810, "NVIDIA")],
        set_alias=("收入", "revenue"),
        set_quarters=2
    ))
    assert p.watchlist == [Company("NVDA", 1045810, "NVIDIA")]
    assert p.metric_aliases["收入"] == "revenue" and p.default_quarters == 2
    assert ProfileStore(tmp_path / "p.json").load().default_quarters == 2  # persisted
