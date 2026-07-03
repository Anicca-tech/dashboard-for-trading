"""
Fetches price/indicator data for watchlist tickers listed in config.json
and writes data/watchlist_prices.json. Field names match wlParseChart in
index.html so the browser can consume the file without any transformation.
"""

import json
import os
from datetime import datetime, timezone

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("yfinance not installed. Run: pip install yfinance")

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
DATA_DIR    = os.path.join(ROOT, "data")

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)


def _ema(closes, period):
    k = 2 / (period + 1)
    v = sum(closes[:period]) / period
    for p in closes[period:]:
        v = p * k + v * (1 - k)
    return v


def _sma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _atr_pct(highs, lows, closes, period=14):
    trs = [
        max(highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    if len(trs) < period:
        return None
    return round(sum(trs[-period:]) / period / closes[-1] * 100, 2)


def _adr_pct(highs, lows, closes, period=20):
    n    = min(period, len(closes))
    vals = [
        (highs[i] - lows[i]) / closes[i]
        for i in range(-n, 0)
        if closes[i] > 0
    ]
    return round(sum(vals) / len(vals) * 100, 2) if vals else None


def _rel_vol(volumes):
    """Today's volume divided by the 20-day average of the *previous* days."""
    if len(volumes) < 2:
        return None
    past20 = volumes[-21:-1]
    if not past20:
        return None
    avg = sum(past20) / len(past20)
    return round(volumes[-1] / avg, 2) if avg > 0 else None


def build_entry(sym, hist):
    closes  = hist["Close"].dropna().tolist()
    highs   = hist["High"].dropna().tolist()
    lows    = hist["Low"].dropna().tolist()
    volumes = hist["Volume"].dropna().tolist()

    if len(closes) < 22:
        print(f"  {sym}: insufficient history ({len(closes)} bars), skipping")
        return None

    price = closes[-1]

    ema21 = _ema(closes, 21)
    s50   = _sma(closes, 50)
    s200  = _sma(closes, 200)

    return {
        "price":    round(price, 4),
        "change1d": round((price - closes[-2]) / closes[-2] * 100, 2) if closes[-2] else None,
        "atr_pct":  _atr_pct(highs, lows, closes, 14),
        "adr_pct":  _adr_pct(highs, lows, closes, 20),
        "ema21d":   round((price - ema21) / ema21 * 100, 2) if ema21 else None,
        "sma50d":   round((price - s50)   / s50   * 100, 2) if s50   else None,
        "sma200d":  round((price - s200)  / s200  * 100, 2) if s200  else None,
        "rel_vol":  _rel_vol(volumes),
    }


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    tickers = CONFIG.get("watchlist", {}).get("tickers", [])
    if not tickers:
        print("No tickers in config.json watchlist.tickers — writing empty file.")
        out = {"updated": datetime.now(timezone.utc).isoformat(), "tickers": {}}
        with open(os.path.join(DATA_DIR, "watchlist_prices.json"), "w") as f:
            json.dump(out, f, separators=(",", ":"))
        return

    print(f"Fetching {len(tickers)} watchlist tickers: {', '.join(tickers)}")

    try:
        raw = yf.download(
            tickers,
            period="1y",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        raise SystemExit(f"yfinance download failed: {e}")

    results = {}
    for sym in tickers:
        try:
            hist = raw[sym] if len(tickers) > 1 else raw
            hist = hist.dropna(subset=["Close"])
            entry = build_entry(sym, hist)
            if entry:
                results[sym.upper()] = entry
                print(f"  {sym}: ${entry['price']}  1d={entry['change1d']}%")
        except Exception as e:
            print(f"  {sym}: error — {e}")

    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "tickers": results,
    }
    out_path = os.path.join(DATA_DIR, "watchlist_prices.json")
    with open(out_path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Wrote {out_path} ({len(results)}/{len(tickers)} tickers)")


if __name__ == "__main__":
    main()
