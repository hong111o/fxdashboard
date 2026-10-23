"""Text commands for changing targets, from WhatsApp, Telegram or the "Run workflow" form.

  /check                        current rates vs your targets
  /rate GBP/HKD                 latest mid-market rate for any pair
  /list                         show current targets and levels
  /target GBP/HKD 10.05         set a conversion alert's target
  /above AUD/USD 0.68           set a watch's upper level
  /below AUD/USD 0.64           set a watch's lower level
  /clear AUD/USD [above|below]  remove a watch's level(s)
  /pause GBP/JPY                stop alerts for a pair (conversion or watch)
  /resume GBP/JPY               start them again
  /help                         this list

The leading / is optional.
"""

HELP = "Commands:\n" + __doc__.split("\n", 2)[2].rstrip()
CHECK = object()  # returned for /check: the caller replies with a fresh status report


def _num(text):
    try:
        return float(text.replace(",", ""))
    except ValueError:
        raise ValueError(f"{text!r} is not a number")


def _find(items, pair, kind):
    pair = pair.upper()
    for item in items:
        if item["pair"] == pair:
            return item
    known = ", ".join(i["pair"] for i in items) or "none"
    raise ValueError(f"no {kind} for {pair} (known: {known})")


def describe(cfg):
    lines = ["Conversion alerts:"]
    for a in cfg.get("alert", []):
        buying_base = a["buy"] == a["pair"].split("/")[0]
        paused = " (paused)" if a.get("paused") else ""
        lines.append(f"  {a['pair']} {'<=' if buying_base else '>='} {a['target']}  [{a['name']}]{paused}")
    lines.append("Trading watchlist:")
    for w in cfg.get("watch", []):
        levels = [f"{k} {w[k]}" for k in ("below", "above") if k in w]
        paused = " (paused)" if w.get("paused") else ""
        lines.append(f"  {w['pair']}: {', '.join(levels) or 'no levels'}{paused}")
    return "\n".join(lines)


def handle(text, cfg, data, rate_lookup=None):
    """Apply one command to `data` (and the live `cfg`). Returns the reply text, or CHECK.

    `rate_lookup(base, quote)` returns the latest mid-market rate, for /rate.
    """
    parts = text.strip().split()
    if not parts:
        return HELP
    cmd, args = parts[0].lower().lstrip("/").split("@")[0], parts[1:]
    try:
        if cmd in ("help", "start", "?"):
            return HELP
        if cmd in ("check", "status"):
            return CHECK
        if cmd == "rate" and len(args) == 1 and rate_lookup:
            base, _, quote = args[0].upper().partition("/")
            if not (len(base) == 3 and len(quote) == 3):
                raise ValueError("write the pair like GBP/HKD")
            try:
                return f"{base}/{quote} mid-market: {rate_lookup(base, quote):,.4f}"
            except Exception as exc:
                return f"Couldn't get {base}/{quote}: {exc}"
        if cmd in ("list", "targets"):
            return describe(cfg)
        if cmd == "target" and len(args) == 2:
            alert = _find(cfg.get("alert", []), args[0], "conversion alert")
            value = _num(args[1])
            alert["target"] = value
            data["alerts"].setdefault(alert["pair"], {})["target"] = value
            return f"OK: {alert['pair']} target is now {value}"
        if cmd in ("above", "below") and len(args) == 2:
            watch = _find(cfg.get("watch", []), args[0], "watch")
            value = _num(args[1])
            watch[cmd] = value
            data["watches"].setdefault(watch["pair"], {})[cmd] = value
            return f"OK: {watch['pair']} {cmd} level is now {value}"
        if cmd == "clear" and len(args) in (1, 2):
            watch = _find(cfg.get("watch", []), args[0], "watch")
            levels = [args[1].lower()] if len(args) == 2 else ["above", "below"]
            if not set(levels) <= {"above", "below"}:
                raise ValueError("clear takes 'above' or 'below'")
            for level in levels:
                watch.pop(level, None)
                data["watches"].setdefault(watch["pair"], {})[level] = None
            return f"OK: cleared {' and '.join(levels)} for {watch['pair']}"
        if cmd in ("pause", "resume") and len(args) == 1:
            pair, paused, hits = args[0].upper(), cmd == "pause", []
            for section, key in (("alert", "alerts"), ("watch", "watches")):
                for item in cfg.get(section, []):
                    if item["pair"] == pair:
                        item["paused"] = paused
                        data[key].setdefault(pair, {})["paused"] = paused
                        hits.append(section)
            if not hits:
                raise ValueError(f"nothing configured for {pair}")
            return f"OK: {pair} {'paused' if paused else 'resumed'}"
    except ValueError as exc:
        return f"Error: {exc}"
    return f"Unknown command: {text.strip()}\n{HELP}"
