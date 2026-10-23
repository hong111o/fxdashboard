"""Saved settings that override config.toml: targets, levels and paused items.

Stored in data/settings.json, which the GitHub workflow commits back to the repo
whenever it changes, so changes made by command persist and keep a history.

{
  "alerts":  {"GBP/HKD": {"target": 10.05, "paused": false}},
  "watches": {"AUD/USD": {"above": 0.68, "below": 0.64, "paused": false}},
  "telegram_offset": 123456789
}
"""

import json
import os

DEFAULT_PATH = "data/settings.json"


def load(path=DEFAULT_PATH):
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    data.setdefault("alerts", {})
    data.setdefault("watches", {})
    return data


def save(data, path=DEFAULT_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def apply(cfg, data):
    """Merge saved overrides into the loaded config, in place."""
    for a in cfg.get("alert", []):
        a.update(data["alerts"].get(a["pair"], {}))
    for w in cfg.get("watch", []):
        w.update(data["watches"].get(w["pair"], {}))
        for level in ("above", "below"):
            if w.get(level) is None:
                w.pop(level, None)
    return cfg
