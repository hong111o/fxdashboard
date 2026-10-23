"""Check every configured alert, notify on hits, and write a summary report.

Usage:
  python -m fxwatch                  # check and notify
  python -m fxwatch --dry-run        # check and print, never notify or save state
  python -m fxwatch --test-notify    # send a test message to check your setup
"""

import argparse
import datetime as dt
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field

from . import notify, providers, rates


@dataclass
class Result:
    alert: dict
    mid: float                       # mid-market, in BASE/QUOTE terms
    quotes: list = field(default_factory=list)  # (rate, Quote), best first
    low: float = None                # history low/high, in BASE/QUOTE terms
    high: float = None
    errors: list = field(default_factory=list)

    @property
    def base(self):
        return self.alert["pair"].split("/")[0]

    @property
    def buying_base(self):
        return self.alert["buy"] == self.base

    @property
    def best(self):
        return self.quotes[0] if self.quotes else None

    @property
    def checked_rate(self):
        if self.alert.get("basis", "best") == "best" and self.best:
            return self.best[0]
        return self.mid

    @property
    def hit(self):
        target = float(self.alert["target"])
        return self.checked_rate <= target if self.buying_base else self.checked_rate >= target

    def better(self, a, b):
        """True if rate a is better for the user than rate b."""
        return a < b if self.buying_base else a > b


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for a in cfg.get("alert", []):
        base, quote = a["pair"].upper().split("/")
        a["pair"], a["sell"], a["buy"] = f"{base}/{quote}", a["sell"].upper(), a["buy"].upper()
        if {a["sell"], a["buy"]} != {base, quote}:
            raise ValueError(f"alert {a['name']!r}: sell/buy must be the two currencies of {a['pair']}")
    return cfg


def evaluate(alert, cfg):
    sell, buy, amount = alert["sell"], alert["buy"], float(alert["amount"])
    base, quote = alert["pair"].split("/")
    manual = cfg.get("provider", [])

    fee_ccys = {p.get("fee_currency", sell) for p in manual}
    sell_rates = rates.latest_rates(sell, fee_ccys | {buy})  # 1 sell = x ccy
    mid_sell_buy = sell_rates[buy]
    mid = mid_sell_buy if sell == base else 1 / mid_sell_buy
    result = Result(alert, mid)

    def fx_to_sell(ccy):
        return 1.0 if ccy == sell else 1 / sell_rates[ccy]

    all_quotes = providers.manual_quotes(manual, sell, buy, amount, mid_sell_buy, fx_to_sell)
    if cfg.get("wise_comparison", {}).get("enabled", True):
        try:
            all_quotes += providers.wise_quotes(sell, buy, amount)
        except Exception as exc:
            result.errors.append(f"Wise comparison unavailable: {exc}")
    all_quotes.sort(key=lambda q: q.received, reverse=True)
    result.quotes = [(q.pair_rate(base, sell), q) for q in all_quotes]

    try:
        series = [r for _, r in rates.history(base, quote, cfg["settings"].get("history_days", 30))]
        if series:
            result.low, result.high = min(series), max(series)
    except Exception as exc:
        result.errors.append(f"history unavailable: {exc}")
    return result


def should_notify(result, state, settings, now):
    if not result.hit:
        return False
    prev = state.get(result.alert["name"])
    if not prev:
        return True
    hours = (now - dt.datetime.fromisoformat(prev["sent_at"])).total_seconds() / 3600
    if hours >= settings.get("cooldown_hours", 12):
        return True
    improvement = abs(result.checked_rate / prev["rate"] - 1) * 100
    return (result.better(result.checked_rate, prev["rate"])
            and improvement >= settings.get("realert_improvement_pct", 0.5))


def fmt(x):
    return f"{x:,.4f}" if x < 1000 else f"{x:,.2f}"


def message(result, top_n):
    a = result.alert
    want = "<=" if result.buying_base else ">="
    lines = [
        f"FX alert: {a['name']}",
        f"{a['pair']} {fmt(result.checked_rate)} ({a.get('basis', 'best')}) - target {want} {fmt(float(a['target']))}",
        f"Mid-market: {fmt(result.mid)}",
    ]
    if result.low is not None:
        lines.append(f"Last {a.get('history_days', 30)} days: low {fmt(result.low)} / high {fmt(result.high)}")
    if result.quotes:
        lines.append(f"Best for {fmt(float(a['amount']))} {a['sell']} -> {a['buy']}:")
        for rate, q in result.quotes[:top_n]:
            lines.append(f"  {q.provider}: {fmt(q.received)} {a['buy']} (rate {fmt(rate)})")
    return "\n".join(lines)


def summary_markdown(results, now):
    out = [f"## FX Watch - {now:%Y-%m-%d %H:%M} UTC", "",
           "| Alert | Mid | Best all-in | Best provider | Target | Range | Status |",
           "|---|---|---|---|---|---|---|"]
    for r in results:
        a = r.alert
        best = r.best
        want = "≤" if r.buying_base else "≥"
        rng = f"{fmt(r.low)} – {fmt(r.high)}" if r.low is not None else "–"
        out.append(f"| {a['name']} ({a['pair']}) | {fmt(r.mid)} | {fmt(best[0]) if best else '–'} | "
                   f"{best[1].provider if best else '–'} | {want} {fmt(float(a['target']))} | {rng} | "
                   f"{'**HIT**' if r.hit else 'waiting'} |")
    for r in results:
        if not r.quotes:
            continue
        a = r.alert
        out += ["", f"### {a['name']}: {fmt(float(a['amount']))} {a['sell']} → {a['buy']}", "",
                "| Provider | You receive | Rate | vs best | Source |", "|---|---|---|---|---|"]
        top = r.quotes[0][1].received
        for rate, q in r.quotes:
            out.append(f"| {q.provider} | {fmt(q.received)} {a['buy']} | {fmt(rate)} | "
                       f"{(q.received / top - 1) * 100:+.2f}% | {q.source} |")
        for e in r.errors:
            out.append(f"\n> {e}")
    return "\n".join(out) + "\n"


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def run(argv=None):
    ap = argparse.ArgumentParser(prog="fxwatch")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--state", default="state/state.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-notify", action="store_true")
    args = ap.parse_args(argv)

    if args.test_notify:
        channel = notify.send("FX Watch test message - notifications are working.")
        print(f"sent via {channel}" if channel else "no notification channel configured")
        return 0 if channel else 1

    cfg = load_config(args.config)
    settings = cfg.setdefault("settings", {})
    state = load_state(args.state)
    now = dt.datetime.now(dt.timezone.utc)
    results, failed = [], False

    for alert in cfg.get("alert", []):
        alert.setdefault("history_days", settings.get("history_days", 30))
        try:
            r = evaluate(alert, cfg)
        except Exception as exc:
            print(f"[{alert['name']}] failed: {exc}", file=sys.stderr)
            failed = True
            continue
        results.append(r)
        text = message(r, settings.get("top_providers", 3))
        print(text, "\n")
        if not args.dry_run and should_notify(r, state, settings, now):
            try:
                channel = notify.send(text)
                print(f"-> notified via {channel}" if channel else "-> no notification channel configured")
                if channel:
                    state[alert["name"]] = {"sent_at": now.isoformat(), "rate": r.checked_rate}
            except Exception as exc:
                print(f"-> notification failed: {exc}", file=sys.stderr)
                failed = True

    report = summary_markdown(results, now)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report)
    if not args.dry_run:
        os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
        with open(args.state, "w") as f:
            json.dump(state, f, indent=2)
    return 1 if failed else 0
