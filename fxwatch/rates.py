"""Mid-market rates and recent history.

Primary source is Frankfurter (ECB reference rates, published once per working
day). open.er-api.com is used as a fallback for the latest rates.
"""

import datetime as dt

from .http import get_json

FRANKFURTER = "https://api.frankfurter.app"
ER_API = "https://open.er-api.com/v6/latest"


def latest_rates(base, symbols):
    """Return {symbol: rate} meaning 1 `base` = rate `symbol`."""
    symbols = sorted(set(symbols) - {base})
    if not symbols:
        return {}
    try:
        data = get_json(f"{FRANKFURTER}/latest", {"from": base, "to": ",".join(symbols)})
        rates = data["rates"]
    except Exception:
        data = get_json(f"{ER_API}/{base}")
        rates = data["rates"]
    return {s: float(rates[s]) for s in symbols}


def history(base, quote, days):
    """Return a list of (date, rate) for the last `days` days, oldest first."""
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    data = get_json(f"{FRANKFURTER}/{start.isoformat()}..{end.isoformat()}", {"from": base, "to": quote})
    return sorted((day, float(r[quote])) for day, r in data["rates"].items())
