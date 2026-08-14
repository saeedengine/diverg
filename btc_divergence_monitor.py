"""
BTC 5-minute RSI Divergence Monitor
------------------------------------
Fetches recent 5-minute BTC/USD candles, computes RSI(14), looks for regular
bullish/bearish divergence between price pivots and RSI pivots, and sends a
Telegram alert when a divergence is confirmed on a completed candle.

Divergence rule (same rule used for the gold RSI-divergence backtest):
  BEARISH (sell):  2nd price high > 1st price high
                    AND 2nd RSI high <= 1st RSI high
                    AND at least one of the two RSI highs > OVERBOUGHT (70)
  BULLISH (buy):    2nd price low < 1st price low
                    AND 2nd RSI low >= 1st RSI low
                    AND at least one of the two RSI lows < OVERSOLD (30)

Data source: Kraken public OHLC API (no key required, no geo-blocking issues
for cloud/CI IPs, unlike some other exchanges).

State: last-alerted pivot timestamp is stored in state.json and committed
back to the repo by the GitHub Actions workflow, so the same divergence
doesn't trigger a duplicate alert every 5 minutes.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PAIR = "XBTUSD"          # Kraken symbol for BTC/USD
INTERVAL_MIN = 5          # candle size in minutes
RSI_PERIOD = 14
OVERBOUGHT = 70
OVERSOLD = 30
PIVOT_LOOKBACK = 6        # bars on each side required to confirm a swing pivot
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_candles(pair=PAIR, interval=INTERVAL_MIN):
    """Return a list of closed candles: [time, open, high, low, close]."""
    params = urllib.parse.urlencode({"pair": pair, "interval": interval})
    url = f"{KRAKEN_URL}?{params}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.loads(resp.read().decode())

    if data.get("error"):
        raise RuntimeError(f"Kraken API error: {data['error']}")

    result = data["result"]
    key = next(k for k in result.keys() if k != "last")
    raw = result[key]

    candles = [
        {
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
        }
        for row in raw
    ]

    # Kraken's last row is typically the still-forming candle. Drop it so we
    # only evaluate signals on fully closed candles.
    now = time.time()
    if candles and candles[-1]["time"] + interval * 60 > now:
        candles = candles[:-1]

    return candles


# ---------------------------------------------------------------------------
# RSI (Wilder's smoothing, standard 14-period RSI)
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
# Pivot detection
# ---------------------------------------------------------------------------
def find_pivots(candles, rsi, lookback=PIVOT_LOOKBACK):
    """
    Return two lists of confirmed pivots: pivot_highs, pivot_lows.
    Each pivot is a dict: {index, time, price, rsi}.
    A bar is a pivot high if its high is the max among `lookback` bars on
    each side; pivot low is analogous for lows. Requires both price and RSI
    data to exist at that index.
    """
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


# ---------------------------------------------------------------------------
# Divergence detection
# ---------------------------------------------------------------------------
def detect_divergence(pivot_highs, pivot_lows):
    """
    Compare the two most recent confirmed pivot highs (bearish check) and the
    two most recent confirmed pivot lows (bullish check). Returns a list of
    signal dicts (0, 1, or 2 entries).
    """
    signals = []

    if len(pivot_highs) >= 2:
        p1, p2 = pivot_highs[-2], pivot_highs[-1]
        if p2["price"] > p1["price"] and p2["rsi"] <= p1["rsi"]:
            if p1["rsi"] > OVERBOUGHT or p2["rsi"] > OVERBOUGHT:
                signals.append({
                    "type": "bearish",
                    "pivot1": p1,
                    "pivot2": p2,
                })

    if len(pivot_lows) >= 2:
        p1, p2 = pivot_lows[-2], pivot_lows[-1]
        if p2["price"] < p1["price"] and p2["rsi"] >= p1["rsi"]:
            if p1["rsi"] < OVERSOLD or p2["rsi"] < OVERSOLD:
                signals.append({
                    "type": "bullish",
                    "pivot1": p1,
                    "pivot2": p2,
                })

    return signals


# ---------------------------------------------------------------------------
# State (dedup so the same divergence doesn't alert every run)
# ---------------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_alerted": {"bearish": None, "bullish": None}, "last_run": None}


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


def format_message(signal, latest_price):
    p1, p2 = signal["pivot1"], signal["pivot2"]
    kind = "BEARISH divergence (overbought)" if signal["type"] == "bearish" else "BULLISH divergence (oversold)"
    arrow = "price higher high, RSI lower high" if signal["type"] == "bearish" else "price lower low, RSI higher low"
    return (
        f"BTC/USD 5m — {kind}\n"
        f"{arrow}\n"
        f"Prior pivot: price {p1['price']:.2f}, RSI {p1['rsi']:.1f}\n"
        f"Latest pivot: price {p2['price']:.2f}, RSI {p2['rsi']:.1f}\n"
        f"Current price: {latest_price:.2f}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID env vars.", file=sys.stderr)
        sys.exit(1)

    candles = fetch_candles()
    if len(candles) < RSI_PERIOD + 2 * PIVOT_LOOKBACK + 2:
        print("Not enough candle history yet.")
        return

    closes = [c["close"] for c in candles]
    rsi = compute_rsi(closes)
    pivot_highs, pivot_lows = find_pivots(candles, rsi)
    signals = detect_divergence(pivot_highs, pivot_lows)

    state = load_state()
    latest_price = closes[-1]
    sent_any = False

    for sig in signals:
        pivot_time = sig["pivot2"]["time"]
        if state["last_alerted"].get(sig["type"]) == pivot_time:
            continue  # already alerted for this exact pivot
        msg = format_message(sig, latest_price)
        send_telegram(token, chat_id, msg)
        state["last_alerted"][sig["type"]] = pivot_time
        sent_any = True
        print(f"Sent {sig['type']} alert for pivot at {pivot_time}")

    if not sent_any:
        print("No new divergence signal this run.")

    state["last_run"] = int(time.time())
    save_state(state)


if __name__ == "__main__":
    main()
