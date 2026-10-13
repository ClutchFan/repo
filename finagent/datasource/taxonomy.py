import pathlib, yaml

_p = pathlib.Path(__file__).with_name("default_metrics.yaml")
_raw = yaml.safe_load(_p.read_text())

METRIC_ALIASES = {k: tuple(f"us-gaap:{n}" for n in v) for k, v in _raw.items()}

def concepts_for(alias):
    return METRIC_ALIASES[alias]

def pick_concept(alias, available):
    for c in concepts_for(alias):
        if c in available:
            return c
    return None
