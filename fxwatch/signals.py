"""Trading signals on a daily rate series: price levels, big moves, breakouts, SMA crosses.

A series is a list of (date, rate) for working days, oldest first. Rates are in
BASE/QUOTE terms (e.g. AUD/USD = USD per 1 AUD).
"""

from dataclasses import dataclass


@dataclass
class Signal:
    key: str        # identity for de-duplication; dated keys fire once per data day
    text: str
    dated: bool     # False -> level signal, repeats after the cooldown while it holds


def sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def calendar_days_needed(watch):
    """How much history to fetch so the longest look-back has enough working days."""
    longest = max(int(watch.get("breakout_days", 0)), int(watch.get("sma_days", 0)) + 1, 2)
    return int(longest * 1.5) + 10


def compute(watch, series):
    if len(series) < 2:
        return []
    day, last = series[-1]
    values = [r for _, r in series]
    prev = values[-2]
    pair = watch["pair"]
    out = []

    if "below" in watch and last <= float(watch["below"]):
        out.append(Signal(f"{pair}:below", f"at/below your level {watch['below']}", False))
    if "above" in watch and last >= float(watch["above"]):
        out.append(Signal(f"{pair}:above", f"at/above your level {watch['above']}", False))

    move = (last / prev - 1) * 100
    if "move_pct" in watch and abs(move) >= float(watch["move_pct"]):
        out.append(Signal(f"{pair}:move:{day}", f"{'up' if move > 0 else 'down'} {move:+.2f}% on the day", True))

    n = int(watch.get("breakout_days", 0))
    if n and len(values) > n:
        prior = values[-n - 1:-1]
        if last > max(prior):
            out.append(Signal(f"{pair}:high:{day}", f"new {n}-day high (prev {max(prior):.4f})", True))
        elif last < min(prior):
            out.append(Signal(f"{pair}:low:{day}", f"new {n}-day low (prev {min(prior):.4f})", True))

    n = int(watch.get("sma_days", 0))
    if n and len(values) > n:
        today, yday = sma(values, n), sma(values[:-1], n)
        if prev <= yday and last > today:
            out.append(Signal(f"{pair}:sma_up:{day}", f"crossed above its {n}-day average ({today:.4f})", True))
        elif prev >= yday and last < today:
            out.append(Signal(f"{pair}:sma_down:{day}", f"crossed below its {n}-day average ({today:.4f})", True))
    return out
