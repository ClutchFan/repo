import json
import pathlib
import dataclasses
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple, Optional
from finagent.models import Company


@dataclass
class Profile:
    watchlist: List = field(default_factory=list)
    metric_aliases: Dict = field(default_factory=dict)
    default_quarters: int = 4
    preferences: Dict = field(default_factory=lambda: {"units": "USD", "scaling": "millions"})
    confirmed_resolutions: Dict = field(default_factory=dict)


@dataclass
class ProfileUpdate:
    add_watchlist: List = field(default_factory=list)
    set_alias: Optional[Tuple[str, str]] = None
    set_quarters: Optional[int] = None


class ProfileStore:
    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)

    def load(self) -> Profile:
        if not self.path.exists():
            return Profile()
        d = json.loads(self.path.read_text())
        w = [Company(**c) for c in d.get("watchlist", [])]
        return Profile(
            w,
            d.get("metric_aliases", {}),
            d.get("default_quarters", 4),
            d.get("preferences", {"units": "USD", "scaling": "millions"}),
            d.get("confirmed_resolutions", {})
        )

    def save(self, p: Profile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(p)
        d["watchlist"] = [asdict(c) for c in p.watchlist]
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2))

    def apply_update(self, u: ProfileUpdate) -> Profile:
        p = self.load()
        for c in u.add_watchlist:
            if c not in p.watchlist:
                p.watchlist.append(c)
        if u.set_alias:
            p.metric_aliases[u.set_alias[0]] = u.set_alias[1]
        if u.set_quarters:
            p.default_quarters = u.set_quarters
        self.save(p)
        return p
