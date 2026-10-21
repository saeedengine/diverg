"""
Daily RSI Divergence Monitor (BTC + major forex pairs + gold) -> Telegram
---------------------------------------------------------------------------
Checks DAILY candles for each symbol in SYMBOLS and alerts when price and RSI
diverge, confirmed by the NEXT candle closing in the opposite direction.

BULLISH rule (the bearish rule is the exact mirror image):
  1. A "low" is a RED candle that is followed by a GREEN candle (closed).
  2. Only a red candle that CLOSES LOWER than the previous low is considered.
     Small red-then-green dips that close higher than the previous low are ignored.
  3. Divergence: RSI at the new low is equal or higher than RSI at the previous low.
  4. At least one of the RSI values involved must be in the oversold zone
     (below OVERSOLD). For bearish: above OVERBOUGHT.
  5. The alert fires when the green candle after the new low has closed.
  6. TRIPLE divergence: three lows in a row, each closing lower than the one
     before, with RSI equal or higher each time. Sent instead of the normal
     alert when the third low is confirmed.

Bearish mirror: green candle followed by a red candle, closing HIGHER than the
previous high, RSI equal or LOWER, overbought zone.

Data sources:
  - BTC/USD  -> Kraken public API (no key needed)
  - Forex/gold -> Twelve Data (free key, TWELVE_DATA_API_KEY)

To add or remove a pair, edit the SYMBOLS list below (one line per pair).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# name = label shown in alerts, source = "kraken" or "twelvedata",
# symbol = the provider's own symbol, decimals = price decimals in alerts
SYMBOLS = [
    {"name": "BTC/USD", "source": "kraken",     "symbol": "XBTUSD",  "decimals": 2},
    {"name": "EUR/USD", "source": "twelvedata", "symbol": "EUR/USD", "decimals": 5},
    {"name": "GBP/USD", "source": "twelvedata", "symbol": "GBP/USD", "decimals": 5},
    {"name": "XAU/USD", "source": "twelvedata", "symbol": "XAU/USD", "decimals": 2},  # gold
    {"name": "USD/CHF", "source": "twelvedata", "symbol": "USD/CHF", "decimals": 5},
    {"name": "USD/CAD", "source": "twelvedata", "symbol": "USD/CAD", "decimals": 5},
    {"name": "NZD/USD", "source": "twelvedata", "symbol": "NZD/USD", "decimals": 5},
    {"name": "USD/JPY", "source": "twelvedata", "symbol": "USD/JPY", "decimals": 3},
    {"name": "AUD/USD", "source": "twelvedata", "symbol": "AUD/USD", "decimals": 5},
]

TIMEFRAME_LABEL = "1D"
RSI_PERIOD = 14
OVERBOUGHT = 65           # bearish: at least one RSI value must be above this
OVERSOLD = 35             # bullish: at least one RSI value must be below this
RSI_EQUAL_TOLERANCE = 0.5 # "equal or higher" RSI also accepts a tiny dip (data providers differ slightly); set 0 for exact
MAX_PIVOT_GAP = 30        # a previous low/high older than this many daily candles is not compared with
MAX_SIGNAL_AGE = 3        # only alert if the confirming candle is among the last N closed candles

TD_OUTPUT_SIZE = 300      # daily candles fetched per symbol (costs 1 credit regardless)
TD_SECONDS_BETWEEN_CALLS = 8   # keeps us under Twelve Data's free 8-requests/minute limit

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"


# ---------------------------------------------------------------------------
# Data fetching — both return closed daily candles, oldest first,
# each: {time: "YYYY-MM-DD", open, high, low, close}
# ---------------------------------------------------------------------------
def drop_forming_candle(candles):
    """Remove the last candle if its UTC day hasn't finished yet."""
    if not candles:
        return candles
    last_start = datetime.strptime(candles[-1]["time"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if last_start + timedelta(days=1) > datetime.now(timezone.utc):
        return candles[:-1]
    return candles


def fetch_kraken(pair):
    params = urllib.parse.urlencode({"pair": pair, "interval": 1440})
    with urllib.request.urlopen(f"{KRAKEN_URL}?{params}", timeout=20) as resp:
        data = json.loads(resp.read().decode())
    if data.get("error"):
        raise RuntimeError(f"Kraken error: {data['error']}")
    result = data["result"]
    key = next(k for k in result.keys() if k != "last")
    candles = [
        {
            "time": datetime.fromtimestamp(int(row[0]), tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
        }
        for row in result[key]
    ]
    return drop_forming_candle(candles)


def fetch_twelvedata(symbol, api_key):
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": "1day",
        "outputsize": TD_OUTPUT_SIZE,
        "timezone": "UTC",
        "apikey": api_key,
    })
    with urllib.request.urlopen(f"{TWELVE_DATA_URL}?{params}", timeout=30) as resp:
        data = json.loads(resp.read().decode())
    if data.get("status") == "error" or "values" not in data:
        raise RuntimeError(f"Twelve Data error: {data.get('message', data)}")
    candles = [
        {
            "time": v["datetime"][:10],  # daily bars may come back as date or date+time
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
        }
        for v in data["values"]
    ]
    candles.sort(key=lambda c: c["time"])
    return drop_forming_candle(candles)


# ---------------------------------------------------------------------------
# RSI (Wilder's smoothing, standard 14-period)
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
# Lows/highs + divergence (candle-confirmed)
# ---------------------------------------------------------------------------
SIDES = {
    "bullish": {"pivot": "R", "confirm": "G"},   # red candle, then green candle
    "bearish": {"pivot": "G", "confirm": "R"},   # green candle, then red candle
}


def direction(c):
    if c["close"] > c["open"]:
        return "G"
    if c["close"] < c["open"]:
        return "R"
    return None


def more_extreme(side, new_close, ref_close):
    """bullish: closes LOWER than the previous low; bearish: closes HIGHER than the previous high."""
    return new_close < ref_close if side == "bullish" else new_close > ref_close


def rsi_confirms(side, rsi_new, rsi_ref):
    """bullish: RSI equal or higher; bearish: RSI equal or lower (small tolerance)."""
    if side == "bullish":
        return rsi_new >= rsi_ref - RSI_EQUAL_TOLERANCE
    return rsi_new <= rsi_ref + RSI_EQUAL_TOLERANCE


def in_zone(side, values):
    if side == "bullish":
        return any(v < OVERSOLD for v in values)
    return any(v > OVERBOUGHT for v in values)


def build_pivots(candles, rsi, side):
    """
    Walk the candles in order and keep a chain of accepted lows (or highs).
    A candidate is a red candle followed by a green one (mirror for bearish).
    If there is a recent previous low, the candidate is only accepted when it
    closes lower than that low; otherwise it is a small dip and is ignored.
    """
    cfg = SIDES[side]
    pivots = []
    for i in range(len(candles) - 1):
        if rsi[i] is None:
            continue
        if direction(candles[i]) != cfg["pivot"] or direction(candles[i + 1]) != cfg["confirm"]:
            continue
        cand = {
            "index": i,
            "time": candles[i]["time"],
            "close": candles[i]["close"],
            "rsi": rsi[i],
            "confirm_index": i + 1,
            "confirm_time": candles[i + 1]["time"],
            "confirm_close": candles[i + 1]["close"],
            "prev": None,
        }
        if pivots:
            ref = pivots[-1]
            if i - ref["index"] <= MAX_PIVOT_GAP:
                if not more_extreme(side, cand["close"], ref["close"]):
                    continue  # small dip: ignored
                cand["prev"] = ref
            # else: previous low is too old -> this candidate starts a new chain
        pivots.append(cand)
    return pivots


def find_signals(candles, rsi):
    """Return every double/triple divergence found in the series (any age)."""
    signals = []
    for side in ("bullish", "bearish"):
        for x in build_pivots(candles, rsi, side):
            run = [x]
            node = x
            while node["prev"] is not None and len(run) < 6 and rsi_confirms(side, node["rsi"], node["prev"]["rsi"]):
                node = node["prev"]
                run.insert(0, node)
            if len(run) < 2:
                continue
            if not in_zone(side, [p["rsi"] for p in run]):
                continue
            kind = "triple" if len(run) >= 3 else "double"
            signals.append({"side": side, "kind": kind, "pivots": run, "key": f"{side}_{kind}"})
    return signals


# ---------------------------------------------------------------------------
# State (per-symbol dedup so the same divergence isn't re-sent every run)
# ---------------------------------------------------------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_run": None}


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


def format_message(cfg, sig):
    d = cfg["decimals"]
    bull = sig["side"] == "bullish"
    pivots = sig["pivots"]
    zone = "oversold" if bull else "overbought"
    title = ("TRIPLE " if sig["kind"] == "triple" else "") + sig["side"].upper() + " divergence"
    what = "lows" if bull else "highs"
    lines = [
        f"{cfg['name']} {TIMEFRAME_LABEL} — {title} ({zone} zone)",
        ("Price closed lower each time, RSI equal or higher" if bull
         else "Price closed higher each time, RSI equal or lower"),
    ]
    for n, p in enumerate(pivots, 1):
        lines.append(f"{what[:-1].capitalize()} {n} ({p['time']}): close {p['close']:.{d}f}, RSI {p['rsi']:.1f}")
    last = pivots[-1]
    lines.append(
        f"Confirmed: {'green' if bull else 'red'} candle closed {last['confirm_time']} at {last['confirm_close']:.{d}f}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-symbol check
# ---------------------------------------------------------------------------
def fetch_for(cfg, td_key):
    if cfg["source"] == "kraken":
        return fetch_kraken(cfg["symbol"])
    # one retry after a minute if Twelve Data says we hit a rate limit
    try:
        return fetch_twelvedata(cfg["symbol"], td_key)
    except RuntimeError as exc:
        if "limit" in str(exc).lower() or "credits" in str(exc).lower():
            print(f"[{cfg['name']}] rate limited, waiting 65s and retrying once...")
            time.sleep(65)
            return fetch_twelvedata(cfg["symbol"], td_key)
        raise


def check_symbol(cfg, state, tg_token, chat_id, td_key):
    candles = fetch_for(cfg, td_key)
    n = len(candles)
    if n < RSI_PERIOD + 10:
        print(f"[{cfg['name']}] not enough candle history.")
        return

    rsi = compute_rsi([c["close"] for c in candles])
    signals = [s for s in find_signals(candles, rsi) if s["pivots"][-1]["confirm_index"] >= n - MAX_SIGNAL_AGE]

    sym_state = state.setdefault(cfg["name"], {})
    last_alerted = sym_state.setdefault("last_alerted", {})
    sent_any = False
    for sig in signals:
        pivot_time = sig["pivots"][-1]["time"]
        if last_alerted.get(sig["key"]) == pivot_time:
            continue  # already alerted for this exact low/high
        send_telegram(tg_token, chat_id, format_message(cfg, sig))
        last_alerted[sig["key"]] = pivot_time  # only recorded if the send succeeded
        sent_any = True
        print(f"[{cfg['name']}] sent {sig['key']} alert for {pivot_time}")

    if not sent_any:
        print(f"[{cfg['name']}] no new divergence signal.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    td_key = os.environ.get("TWELVE_DATA_API_KEY")

    missing = [n for n, v in [("TELEGRAM_BOT_TOKEN", tg_token), ("TELEGRAM_CHAT_ID", chat_id)] if not v]
    if any(c["source"] == "twelvedata" for c in SYMBOLS) and not td_key:
        missing.append("TWELVE_DATA_API_KEY")
    if missing:
        print(f"Missing required secrets: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    failures = []
    last_td_call = 0.0

    for cfg in SYMBOLS:
        if cfg["source"] == "twelvedata":
            wait = TD_SECONDS_BETWEEN_CALLS - (time.time() - last_td_call)
            if wait > 0 and last_td_call:
                time.sleep(wait)
            last_td_call = time.time()
        try:
            check_symbol(cfg, state, tg_token, chat_id, td_key)
        except urllib.error.HTTPError as exc:
            failures.append(cfg["name"])
            print(f"[{cfg['name']}] HTTP error {exc.code}: {exc.reason}", file=sys.stderr)
        except Exception as exc:  # one bad symbol must not stop the others
            failures.append(cfg["name"])
            print(f"[{cfg['name']}] failed: {exc}", file=sys.stderr)

    state["last_run"] = int(time.time())
    save_state(state)

    if failures:
        print(f"Finished with failures: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
