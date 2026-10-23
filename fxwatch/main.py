"""Check every configured alert, notify on hits, and write a summary report.

Usage:
  python -m fxwatch                  # check and notify
  python -m fxwatch --dry-run        # check and print, never notify or save state
  python -m fxwatch --test-notify    # send a test message to check your setup
  python -m fxwatch --command "/target GBP/HKD 10.05"   # change a saved setting
"""

import argparse
import datetime as dt
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field

from . import commands, notify, providers, rates, signals, store


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


@dataclass
class WatchResult:
    watch: dict
    series: list                     # (date, rate), oldest first
    signals: list = field(default_factory=list)

    @property
    def last(self):
        return self.series[-1][1]

    @property
    def day_change(self):
        return (self.series[-1][1] / self.series[-2][1] - 1) * 100 if len(self.series) > 1 else None


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for a in cfg.get("alert", []):
        base, quote = a["pair"].upper().split("/")
        a["pair"], a["sell"], a["buy"] = f"{base}/{quote}", a["sell"].upper(), a["buy"].upper()
        if {a["sell"], a["buy"]} != {base, quote}:
            raise ValueError(f"alert {a['name']!r}: sell/buy must be the two currencies of {a['pair']}")
    for w in cfg.get("watch", []):
        base, quote = w["pair"].upper().split("/")
        w["pair"] = f"{base}/{quote}"
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


def evaluate_watch(watch):
    base, quote = watch["pair"].split("/")
    series = rates.history(base, quote, signals.calendar_days_needed(watch))
    return WatchResult(watch, series, signals.compute(watch, series))


def new_signals(result, state, settings, now):
    fresh = []
    for s in result.signals:
        prev = state.get(s.key)
        if prev is None:
            fresh.append(s)
        elif not s.dated:
            hours = (now - dt.datetime.fromisoformat(prev["sent_at"])).total_seconds() / 3600
            if hours >= settings.get("cooldown_hours", 12):
                fresh.append(s)
    return fresh


def watch_message(result, sigs):
    w = result.watch
    lines = [f"FX watch: {w['pair']} {fmt(result.last)} (as of {result.series[-1][0]})"]
    lines += [f"- {s.text}" for s in sigs]
    if result.day_change is not None:
        lines.append(f"Day change: {result.day_change:+.2f}%")
    if w.get("note"):
        lines.append(w["note"])
    return "\n".join(lines)


def prune_state(state, now, days=30):
    cutoff = now - dt.timedelta(days=days)
    return {k: v for k, v in state.items() if dt.datetime.fromisoformat(v["sent_at"]) >= cutoff}


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


def summary_markdown(results, now, watches=()):
    out = [f"## FX Watch - {now:%Y-%m-%d %H:%M} UTC", "", "### Conversion targets", "",
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
    if watches:
        out += ["", "### Trading watchlist", "",
                "| Pair | Last | Day | Range (look-back) | Signals |", "|---|---|---|---|---|"]
        for w in watches:
            vals = [r for _, r in w.series]
            day = f"{w.day_change:+.2f}%" if w.day_change is not None else "–"
            sigs = "; ".join(s.text for s in w.signals) or "–"
            out.append(f"| {w.watch['pair']} | {fmt(w.last)} | {day} | {fmt(min(vals))} – {fmt(max(vals))} | {sigs} |")
    return "\n".join(out) + "\n"


def load_state(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def process_commands(args, cfg, saved):
    """Apply --command arguments and new Telegram messages; save settings if anything changed."""
    before = json.dumps(saved, sort_keys=True)
    texts = [t for c in args.command for t in c.split(";") if t.strip()]
    replies = [commands.handle(text, cfg, saved) for text in texts]
    if not args.dry_run:
        try:
            texts, offset = notify.telegram_commands(saved.get("telegram_offset"))
            if offset is not None:
                saved["telegram_offset"] = offset
        except Exception as exc:
            print(f"reading Telegram commands failed: {exc}", file=sys.stderr)
            texts = []
        for text in texts:
            reply = commands.handle(text, cfg, saved)
            replies.append(reply)
            try:
                notify.telegram_reply(reply)
            except Exception as exc:
                print(f"Telegram reply failed: {exc}", file=sys.stderr)
    for reply in replies:
        print(reply, "\n")
    if not args.dry_run and json.dumps(saved, sort_keys=True) != before:
        store.save(saved, args.settings)
    return replies


def run(argv=None):
    ap = argparse.ArgumentParser(prog="fxwatch")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--state", default="state/state.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-notify", action="store_true")
    ap.add_argument("--settings", default=store.DEFAULT_PATH)
    ap.add_argument("--command", action="append", default=[], help="apply a command, e.g. '/target GBP/HKD 10.05'")
    args = ap.parse_args(argv)

    if args.test_notify:
        channel = notify.send("FX Watch test message - notifications are working.")
        print(f"sent via {channel}" if channel else "no notification channel configured")
        return 0 if channel else 1

    cfg = load_config(args.config)
    settings = cfg.setdefault("settings", {})
    saved = store.load(args.settings)
    store.apply(cfg, saved)
    replies = process_commands(args, cfg, saved)
    now = dt.datetime.now(dt.timezone.utc)
    state = prune_state(load_state(args.state), now)
    results, watches, failed = [], [], False

    def deliver(text):
        nonlocal failed
        try:
            channel = notify.send(text)
            print(f"-> notified via {channel}" if channel else "-> no notification channel configured")
            return channel
        except Exception as exc:
            print(f"-> notification failed: {exc}", file=sys.stderr)
            failed = True

    for alert in cfg.get("alert", []):
        if alert.get("paused"):
            continue
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
        if not args.dry_run and should_notify(r, state, settings, now) and deliver(text):
            state[alert["name"]] = {"sent_at": now.isoformat(), "rate": r.checked_rate}

    for watch in cfg.get("watch", []):
        if watch.get("paused"):
            continue
        try:
            w = evaluate_watch(watch)
        except Exception as exc:
            print(f"[{watch['pair']}] failed: {exc}", file=sys.stderr)
            failed = True
            continue
        if not w.series:
            continue
        watches.append(w)
        fresh = w.signals if args.dry_run else new_signals(w, state, settings, now)
        if not fresh:
            continue
        text = watch_message(w, fresh)
        print(text, "\n")
        if not args.dry_run and deliver(text):
            for s in fresh:
                state[s.key] = {"sent_at": now.isoformat(), "rate": w.last}

    report = summary_markdown(results, now, watches)
    if replies:
        report += "\n### Commands\n\n" + "\n\n".join(f"```\n{r}\n```" for r in replies) + "\n"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report)
    if not args.dry_run:
        os.makedirs(os.path.dirname(args.state) or ".", exist_ok=True)
        with open(args.state, "w") as f:
            json.dump(state, f, indent=2)
    return 1 if failed else 0
