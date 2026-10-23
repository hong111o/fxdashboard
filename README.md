# fxdashboard: FX Watch

A personal FX rate watcher. Every hour it:

1. Fetches mid-market rates for your currency pairs.
2. Compares the **all-in amount you would actually receive** from different
   banks, brokers and transfer services, after their spread and fees.
3. Sends you a **WhatsApp** message (or **Telegram** if WhatsApp isn't set up
   or fails) when a rate reaches your target.
4. Watches a **trading watchlist** (AUD/USD, GBP/AUD, AUD/JPY, NZD/USD,
   USD/JPY, EUR/USD, USD/CAD) for big daily moves, 20-day breakouts, 50-day
   moving-average crosses and your own price levels.
5. Writes a comparison table to the GitHub Actions run summary, which works as
   a simple dashboard.

It runs on GitHub Actions, so there is no server to manage. It uses only the
Python standard library (3.11+).

## Default watchlist

| Alert | Pair | Fires when |
|---|---|---|
| HKD → GBP | GBP/HKD | 1 GBP costs ≤ target HKD (GBP is cheap) |
| USD → GBP | GBP/USD | 1 GBP costs ≤ target USD |
| Japan trip | GBP/JPY | 1 GBP buys ≥ target JPY |
| Europe trip | GBP/EUR | 1 GBP buys ≥ target EUR |

Edit `config.toml` to change targets, amounts or pairs. You only say what you
**sell** and what you **buy**; the alert direction is worked out for you.

`basis = "best"` checks the target against the best rate you can actually get
from a provider. `basis = "mid"` checks it against the mid-market rate.

## Trading watchlist

Each `[[watch]]` in `config.toml` can use any of these signals:

| Setting | Alerts when |
|---|---|
| `below` / `above` | price is at or beyond your level (repeats after the cooldown while it holds) |
| `move_pct` | the daily move is at least this % in either direction |
| `breakout_days` | price makes a new N-working-day high or low |
| `sma_days` | price crosses its N-day simple moving average (possible trend change) |

Signals use daily ECB closing rates, so they suit swing and position trading
(days to weeks), not intraday trading. Each dated signal fires once per
trading day.

## Where the "true" rates come from

- **Live:** Wise's public comparison API (`api.wise.com/v3/comparisons`)
  returns real quotes from Wise and from the banks and transfer providers it
  tracks for each currency route.
- **Manual:** banks and brokers without a public API are priced from the
  `margin_pct` and `fee` you enter in `config.toml`. Your current accounts,
  Hang Seng Bank and Standard Chartered HK, are set up, plus Interactive
  Brokers as an account you are considering. Wise is priced live, so the
  "vs best" column shows how much opening Wise or IBKR would save you.
  **The shipped numbers are placeholders.** To calibrate a bank, compare its
  in-app rate with the mid-market rate at the same moment, and include any
  outward TT fee if you transfer the money to the UK.

Mid-market rates come from [Frankfurter](https://frankfurter.dev) (ECB
reference rates, updated once per working day around 16:00 CET), with
[open.er-api.com](https://www.exchangerate-api.com/docs/free) as a fallback.

## Setup

### 1. WhatsApp via CallMeBot (free, for personal use)

1. Add **+34 644 66 32 62** to your phone contacts (check
   [callmebot.com](https://www.callmebot.com/blog/free-api-whatsapp-messages/)
   for the current number).
2. Send it the WhatsApp message: `I allow callmebot to send me messages`
3. It replies with your API key.

### 2. Telegram fallback (optional, recommended)

1. In Telegram, message **@BotFather**, send `/newbot`, and copy the bot token.
2. Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.

### 3. Add the secrets

Go to **GitHub repo → Settings → Secrets and variables → Actions → New
repository secret**:

| Secret | Example |
|---|---|
| `WHATSAPP_PHONE` | `+447700900123` |
| `CALLMEBOT_APIKEY` | `123456` |
| `TELEGRAM_BOT_TOKEN` | `123456:ABC...` |
| `TELEGRAM_CHAT_ID` | `987654321` |

### 4. Test it

Go to **Actions → FX Watch → Run workflow** and choose **test-notify**, then
**dry-run** to see the comparison table in the run summary.

## Running locally

```bash
python -m fxwatch --dry-run        # print everything, send nothing
python -m fxwatch --test-notify    # send a test message (needs the env vars above)
python -m unittest -v              # run the tests
```

## Notes

- **Alert spam guard:** after an alert fires it stays quiet for
  `cooldown_hours` (default 12), unless the rate improves by another
  `realert_improvement_pct` (default 0.5%).
- **Actions minutes:** hourly runs use about 720 minutes a month. That is free
  for public repos and fits the 2,000 free minutes for private repos.
- **Rate freshness:** mid-market data is daily (ECB). Wise quotes are live, so
  use `basis = "best"` for intraday moves.
