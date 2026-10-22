# Daily RSI Divergence Monitor -> Telegram

Checks DAILY candles for BTC/USD, EUR/USD, GBP/USD, XAU/USD (gold), USD/CHF,
USD/CAD, NZD/USD, USD/JPY and AUD/USD and sends a Telegram alert when price
and RSI(14) diverge AND the next candle has confirmed it.

## The rule (bullish; bearish is the exact mirror)
1. A "low" is a RED candle followed by a GREEN candle (closed).
2. Only a red candle whose lowest point (shadow included) is LOWER than the
   previous accepted low is considered (`PRICE_BASIS = "wick"`). Red-then-green
   candles that do not go lower than the previous low are ignored. Any lower
   low counts, however small (optional margin: `MIN_BREAK_FRACTION`).
   Set `PRICE_BASIS = "close"` to compare closing prices only instead.
3. Divergence: RSI at the new low is equal or higher than RSI at the previous low.
4. At least one RSI value involved must be below 35 (bearish: above 65).
5. The alert fires once the green candle after the new low has closed.
6. TRIPLE divergence: three lows in a row, each lower than the one before,
   RSI equal or higher each time. When the third low is confirmed you get ONE
   "TRIPLE" alert (instead of a normal one). A fourth low in the same chain
   sends another TRIPLE alert, marked "(4 in a row)".

Bearish mirror: GREEN candle followed by a RED candle, going HIGHER than the
previous high (highest point incl. shadow), RSI equal or LOWER, at least one RSI value above 65.

## Upload
Upload everything in this folder to your GitHub repo and replace the old files
(keep `.github/workflows/monitor.yml` inside those folders). If you still have
these old files in the repo, delete them: btc_divergence_monitor.py,
eurusd_divergence_monitor.py, eurusd_state.json,
.github/workflows/eurusd_monitor.yml

## Secrets (Settings -> Secrets and variables -> Actions)
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- TWELVE_DATA_API_KEY   (free key from twelvedata.com; BTC uses Kraken, no key)

## Run it
Actions tab -> "Daily RSI Divergence Monitor" -> Run workflow. The log shows one
line per pair. It then runs by itself 4 times a day (00:20, 06:20, 12:20, 18:20 UTC).

## Settings you can edit (divergence_monitor.py, lines 59-65)
- Line 59 `PRICE_BASIS = "wick"`: "wick" compares lows/highs including shadows;
  "close" compares closing prices only.
- Line 60 `MIN_BREAK_FRACTION = 0.0`: optional (wick mode). A new low/high must
  beat the previous one by at least this share of the average daily range.
  0 = off, any lower low / higher high counts.
- Line 61 `OVERBOUGHT = 65` and line 62 `OVERSOLD = 35`: the RSI zones.
- Line 63 `RSI_EQUAL_TOLERANCE = 0.5`: "equal or higher" RSI also accepts a tiny
  dip (RSI differs a little between data providers). Set 0 for exact.
- Line 64 `MAX_PIVOT_GAP = 30`: a previous low older than 30 daily candles is not
  compared with (a new chain starts).
- Line 65 `MAX_SIGNAL_AGE = 3`: only alert if the confirming candle is among the
  last 3 closed candles (stops old signals firing on first run).
- Pair list: the `SYMBOLS` list (lines 45-55), one line per pair.

## Limits
- Twelve Data free plan: 800 requests/day and 8 per minute. This uses 8
  requests per run x 4 runs = 32 per day. Calls are spaced 8 seconds apart.
- If a pair fails (for example gold on the free plan), the run shows red, the
  log names the pair, and all other pairs are still checked.
