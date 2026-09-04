# RSI Divergence Monitors → Telegram

Two independent monitors in this repo, both using the same divergence rule
(the one used for the original gold backtest):

  BEARISH (sell):  2nd price high > 1st price high
                    AND 2nd RSI high <= 1st RSI high
                    AND at least one of the two RSI highs > 70 (overbought)
  BULLISH (buy):    2nd price low < 1st price low
                    AND 2nd RSI low >= 1st RSI low
                    AND at least one of the two RSI lows < 30 (oversold)

- **BTC/USD** — `btc_divergence_monitor.py`, checks 30min / 1h / 4h, data from Kraken (no API key needed)
- **EUR/USD** — `eurusd_divergence_monitor.py`, checks 30min / 1h / 4h, data from Twelve Data (free API key)

Both send alerts to the same Telegram bot/chat, tagged with which pair and
timeframe triggered (e.g. "BTC/USD 4h — BEARISH divergence...").

## 1. Create your Telegram bot

1. In Telegram, open a chat with **@BotFather**.
2. Send `/newbot` and follow the prompts.
3. Copy the token it gives you (looks like `123456789:AAExample-Token`) —
   this is `TELEGRAM_BOT_TOKEN`.

## 2. Get your chat ID

1. Message your new bot anything (e.g. "hi").
2. Visit (with your real token): `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Find `"chat":{"id":123456789, ...}` — that number is `TELEGRAM_CHAT_ID`.

## 3. Get a free Twelve Data API key (EUR/USD monitor only)

1. Sign up free at twelvedata.com — no card required.
2. Copy your API key from the dashboard. This is `TWELVE_DATA_API_KEY`.
   (Not needed for the BTC monitor — Kraken requires no key.)

## 4. Create the GitHub repo and upload everything

Create a new **public** repository (public keeps Actions minutes free —
frequent runs can exceed the private-repo free tier). Upload every file in
this package, keeping the exact folder structure — the two workflow files
must stay inside `.github/workflows/`.

## 5. Add your secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TWELVE_DATA_API_KEY`

## 6. Turn it on

**Actions** tab → enable workflows if prompted → open each workflow
("BTC RSI Divergence Monitor" and "EUR/USD RSI Divergence Monitor") →
click **Run workflow** to fire a manual test. Check the logs: you should see
one line per timeframe, either "no new divergence signal this run" or
confirmation that an alert was sent.

After that, each workflow runs on its own hourly fallback schedule
automatically — no further setup required. That's enough to get real alerts,
just with up to ~an hour of delay versus checking every 15 minutes.

## Optional: faster checks (~15 min instead of ~1 hour)

GitHub's built-in `schedule:` trigger is best-effort and commonly delayed,
which is why both workflows default to an hourly cadence. To check every 15
minutes instead, have an external scheduler call the GitHub API to trigger
`workflow_dispatch` on a timer. `cron-job.org` is a common free choice for
this, but its interface changes over time — if you want to try it again,
tell me exactly what you see on the page (field names, layout) and I'll
match the instructions to what's actually there instead of guessing. This
step is entirely optional; the monitors work without it.

## Editing the pivot lookback

Both scripts have a `PIVOT_LOOKBACK` constant near the top — this is the
number of candles on each side of a swing point that must confirm it before
it counts as a pivot. Higher = fewer, more reliable signals but more delay
before confirmation; lower = faster but noisier.

- `btc_divergence_monitor.py`, line 47:
  `PIVOT_LOOKBACK = 3        # <-- bars on each side required to confirm a swing pivot`
- `eurusd_divergence_monitor.py`, line 44:
  `PIVOT_LOOKBACK = 3        # <-- bars on each side required to confirm a swing pivot`

Change the `3` to whatever you want on that one line in each file — nothing
else needs to change, since every other place that uses it references this
same constant.

## Notes

- Forex (EUR/USD) is closed on weekends (~Friday 21:00 UTC to Sunday 21:00
  UTC). Crypto (BTC) trades 24/7. No special handling needed either way —
  candles simply stop updating when a market is closed.
- `RSI_PERIOD` (14), `OVERBOUGHT` (70), and `OVERSOLD` (30) are also
  constants near the top of each script if you want to tune those too.
- Each workflow commits its state file back to the repo every run — this is
  how duplicate alerts are avoided, and it also keeps the repo "active" so
  GitHub doesn't auto-disable the schedules after 60 days of no commits.
- These tools only send you information — they don't place trades. Treat any
  alert as something to verify yourself before acting on it.
