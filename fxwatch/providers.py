"""All-in quotes from providers: live Wise comparisons plus manually configured ones.

Every quote is expressed as "send `amount` of the sell currency, receive X of the
buy currency", which makes providers directly comparable after fees and spread.
"""

from dataclasses import dataclass

from .http import get_json

WISE_COMPARISONS = "https://api.wise.com/v3/comparisons/"


@dataclass
class Quote:
    provider: str
    send: float      # amount of sell currency
    received: float  # amount of buy currency after all fees and spread
    source: str      # "live" or "manual"

    def pair_rate(self, pair_base, sell):
        """Effective rate in the alert's BASE/QUOTE terms."""
        if sell == pair_base:
            return self.received / self.send
        return self.send / self.received


def wise_quotes(sell, buy, amount):
    data = get_json(WISE_COMPARISONS, {"sourceCurrency": sell, "targetCurrency": buy, "sendAmount": amount})
    quotes = []
    for p in data.get("providers", []):
        best = max((q for q in p.get("quotes", []) if q.get("receivedAmount")),
                   key=lambda q: q["receivedAmount"], default=None)
        if best:
            quotes.append(Quote(p.get("name") or p.get("alias", "?"), amount, float(best["receivedAmount"]), "live"))
    return quotes


def manual_quotes(providers, sell, buy, amount, mid, fx_to_sell):
    """`mid` = 1 sell -> buy; `fx_to_sell(ccy)` = value of 1 `ccy` in the sell currency."""
    quotes = []
    for p in providers:
        currencies = p.get("currencies")
        if currencies and not {sell, buy} <= set(currencies):
            continue
        fee = float(p.get("fee", 0)) * fx_to_sell(p.get("fee_currency", sell))
        received = (amount - fee) * mid * (1 - float(p.get("margin_pct", 0)) / 100)
        if received > 0:
            quotes.append(Quote(p["name"], amount, received, "manual"))
    return quotes
