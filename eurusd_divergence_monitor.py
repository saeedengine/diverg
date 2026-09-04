"""
EUR/USD Multi-Timeframe RSI Divergence Monitor
------------------------------------------------
Checks EUR/USD on 30-minute, 1-hour, and 4-hour candles for regular RSI
divergence, filtered to only fire when the RSI involved is overbought (>70)
or oversold (<30), and sends a Telegram alert per timeframe when found.

Same divergence rule as the BTC monitor and the original gold backtest:
  BEARISH (sell):  2nd price high > 1st price high
                    AND 2nd RSI high <= 1st RSI high
                    AND at least one of the two RSI highs > OVERBOUGHT (70)
  BULLISH (buy):    2nd price low < 1st price low
                    AND 2nd RSI low >= 1st RSI low
                    AND at least one of the two RSI lows < OVERSOLD (30)

Data source: Twelve Data (https://twelvedata.com) — free tier, needs an API
key (TWELVE_DATA_API_KEY). Supports 30min/1h/4h forex intervals natively.

Note: forex markets are closed on weekends (roughly Friday ~21:00 UTC to
Sunday ~21:00 UTC). No special handling is needed for this — candles simply
stop updating during that window, so there's nothing new to detect, and
everything resumes normally when the market reopens.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOL = "EUR/USD"
TIMEFRAMES = ["30min", "1h", "4h"]     # Twelve Data interval strings
INTERVAL_MINUTES = {"30min": 30, "1h": 60, "4h": 240}
OUTPUT_SIZE = 200

RSI_PERIOD = 14
OVERBOUGHT = 70
OVERSOLD = 30
PIVOT_LOOKBACK = 3        # <-- bars on each side required to confirm a swing pivot (edit this to change lookback)

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eurusd_state.json")
TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_candles(interval, api_key):
    """Return a list of closed candles: [{time, open, high, low, close}]."""
    params = urllib.parse.urlencode({
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": OUTPUT_SIZE,
        "timezone": "UTC",
        "apikey": api_key,
    })
    url = f"{TWELVE_DATA_URL}?{params}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read().decode())

    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error ({interval}): {data.get('message')}")

    candles = [
        {
            "time": v["datetime"],  # "YYYY-MM-DD HH:MM:SS", UTC
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
        }
        for v in data["values"]
    ]
    candles.sort(key=lambda c: c["time"])  # ensure chronological order

    # Drop a still-forming candle so we only evaluate fully closed bars.
    now = datetime.now(timezone.utc)
    last_dt = datetime.strptime(candles[-1]["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if last_dt + timedelta(minutes=INTERVAL_MINUTES[interval]) > now:
        candles = candles[:-1]

    return candles


# ---------------------------------------------------------------------------
# RSI (Wilder's smoothing, standard 14-period RSI) — same as the BTC monitor
# ---------------------------------------------------------------------------
def compute_rsi(closes, period=RSI_PERIOD):
    n = len(closes)
    rsi = [None] * n
    if n < period + 1:
        return rsi

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    rsi[period] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    return rsi


# ---------------------------------------------------------------------------
# Pivot + divergence detection — identical logic to the BTC monitor
# ---------------------------------------------------------------------------
def find_pivots(candles, rsi, lookback=PIVOT_LOOKBACK):
    pivot_highs = []
    pivot_lows = []
    n = len(candles)

    for i in range(lookback, n - lookback):
        if rsi[i] is None:
            continue
        window = candles[i - lookback:i + lookback + 1]
        this_high = candles[i]["high"]
        this_low = candles[i]["low"]

        if all(this_high >= c["high"] for c in window):
            pivot_highs.append({"index": i, "time": candles[i]["time"], "price": this_high, "rsi": rsi[i]})

        if all(this_low <= c["low"] for c in window):
            pivot_lows.append({"index": i, "time": candles[i]["time"], "price": this_low, "rsi": rsi[i]})

    return pivot_highs, pivot_lows


def detect_divergence(pivot_highs, pivot_lows):
    signals = []

    if len(pivot_highs) >= 2:
        p1, p2 = pivot_highs[-2], pivot_highs[-1]
        if p2["price"] > p1["price"] and p2["rsi"] <= p1["rsi"]:
            if p1["rsi"] > OVERBOUGHT or p2["rsi"] > OVERBOUGHT:
                signals.append({"type": "bearish", "pivot1": p1, "pivot2": p2})

    if len(pivot_lows) >= 2:
        p1, p2 = pivot_lows[-2], pivot_lows[-1]
        if p2["price"] < p1["price"] and p2["rsi"] >= p1["rsi"]:
            if p1["rsi"] < OVERSOLD or p2["rsi"] < OVERSOLD:
                signals.append({"type": "bullish", "pivot1": p1, "pivot2": p2})

    return signals


# ---------------------------------------------------------------------------
# State (per-timeframe dedup so the same divergence isn't re-sent every run)
# ---------------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {tf: {"last_alerted": {"bearish": None, "bullish": None}} for tf in TIMEFRAMES} | {"last_run": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def format_message(timeframe, signal, latest_price):
    p1, p2 = signal["pivot1"], signal["pivot2"]
    kind = "BEARISH divergence (overbought)" if signal["type"] == "bearish" else "BULLISH divergence (oversold)"
    arrow = "price higher high, RSI lower high" if signal["type"] == "bearish" else "price lower low, RSI higher low"
    return (
        f"EUR/USD {timeframe} — {kind}\n"
        f"{arrow}\n"
        f"Prior pivot: price {p1['price']:.5f}, RSI {p1['rsi']:.1f}\n"
        f"Latest pivot: price {p2['price']:.5f}, RSI {p2['rsi']:.1f}\n"
        f"Current price: {latest_price:.5f}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    td_key = os.environ.get("TWELVE_DATA_API_KEY")
    if not telegram_token or not chat_id or not td_key:
        print("Missing TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, or TWELVE_DATA_API_KEY env vars.", file=sys.stderr)
        sys.exit(1)

    state = load_state()

    for tf in TIMEFRAMES:
        try:
            candles = fetch_candles(tf, td_key)
        except Exception as exc:
            print(f"[{tf}] fetch failed: {exc}", file=sys.stderr)
            continue

        if len(candles) < RSI_PERIOD + 2 * PIVOT_LOOKBACK + 2:
            print(f"[{tf}] not enough candle history yet.")
            continue

        closes = [c["close"] for c in candles]
        rsi = compute_rsi(closes)
        pivot_highs, pivot_lows = find_pivots(candles, rsi)
        signals = detect_divergence(pivot_highs, pivot_lows)

        latest_price = closes[-1]
        tf_state = state.setdefault(tf, {"last_alerted": {"bearish": None, "bullish": None}})

        sent_any = False
        for sig in signals:
            pivot_time = sig["pivot2"]["time"]
            if tf_state["last_alerted"].get(sig["type"]) == pivot_time:
                continue  # already alerted for this exact pivot
            msg = format_message(tf, sig, latest_price)
            send_telegram(telegram_token, chat_id, msg)
            tf_state["last_alerted"][sig["type"]] = pivot_time
            sent_any = True
            print(f"[{tf}] sent {sig['type']} alert for pivot at {pivot_time}")

        if not sent_any:
            print(f"[{tf}] no new divergence signal this run.")

        time.sleep(1)  # stay well under Twelve Data's per-minute rate limit

    state["last_run"] = int(time.time())
    save_state(state)


if __name__ == "__main__":
    main()
