"""
Fetches market data for all instruments in config.json and writes to data/market.json
and data/sparklines.json. Run by GitHub Actions every 5 minutes during market hours.
"""

import json
import os
import time
from datetime import datetime, timezone
import requests

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("yfinance not installed. Run: pip install yfinance requests")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
DATA_DIR = os.path.join(ROOT, "data")

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

SPARKLINE_DAYS = 10


def ema(prices, period):
    k = 2 / (period + 1)
    result = [prices[0]]
    for p in prices[1:]:
        result.append(p * k + result[-1] * (1 - k))
    return result


def sma(prices, period):
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def grade(closes):
    if len(closes) < 50:
        return "?"
    e10 = ema(closes, 10)[-1]
    e21 = ema(closes, 21)[-1]
    s50 = sma(closes, 50)
    if e10 > e21 > s50:
        return "A"
    if e10 < e21 < s50:
        return "C"
    return "B"


def pct_change(new, old):
    if old == 0 or old is None:
        return None
    return round((new - old) / abs(old) * 100, 2)


def atr(highs, lows, closes, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr_val = sum(trs[-period:]) / period
    return round(atr_val / closes[-1] * 100, 2)


def adr(highs, lows, period=20):
    adrs = [(highs[i] - lows[i]) / lows[i] * 100 for i in range(-period, 0) if lows[i] > 0]
    return round(sum(adrs) / len(adrs), 2) if adrs else None


def dist_from_52wk_high(closes, highs):
    high_52 = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    return round((closes[-1] - high_52) / high_52 * 100, 2)


def build_instrument(symbol, label, ticker_obj, hist):
    closes = hist["Close"].tolist()
    highs  = hist["High"].tolist()
    lows   = hist["Low"].tolist()

    if len(closes) < 2:
        return None

    price = closes[-1]
    prev_close = closes[-2] if len(closes) > 1 else closes[-1]

    # Period returns
    d1  = pct_change(price, closes[-2]) if len(closes) >= 2  else None
    d5  = pct_change(price, closes[-6]) if len(closes) >= 6  else None
    d20 = pct_change(price, closes[-21]) if len(closes) >= 21 else None
    d50 = pct_change(price, closes[-51]) if len(closes) >= 51 else None

    sparkline = [round(c, 4) for c in closes[-SPARKLINE_DAYS:]]

    return {
        "symbol": symbol,
        "label": label,
        "price": round(price, 4),
        "prev_close": round(prev_close, 4),
        "change_1d": d1,
        "change_1w": d5,
        "change_20d": d20,
        "change_50d": d50,
        "atr_pct": atr(highs, lows, closes),
        "adr_pct": adr(highs, lows),
        "dist_52wk_high": dist_from_52wk_high(closes, highs),
        "grade": grade(closes),
        "sparkline": sparkline,
        "updated": datetime.now(timezone.utc).isoformat(),
    }


def fetch_yahoo_group(instruments):
    symbols = [i["symbol"] for i in instruments]
    label_map = {i["symbol"]: i["label"] for i in instruments}
    results = {}

    try:
        # Batch download 1y daily for all symbols
        data = yf.download(
            symbols,
            period="1y",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"yfinance batch download failed: {e}")
        return results

    for sym in symbols:
        try:
            if len(symbols) == 1:
                hist = data
            else:
                hist = data[sym]

            hist = hist.dropna(subset=["Close"])
            if len(hist) < 2:
                print(f"  Insufficient data for {sym}")
                continue

            entry = build_instrument(sym, label_map[sym], None, hist)
            if entry:
                results[sym] = entry
        except Exception as e:
            print(f"  Error processing {sym}: {e}")

    return results


def fetch_coingecko():
    cryptos = CONFIG["instruments"]["crypto"]
    results = {}
    for c in cryptos:
        coin_id = c["symbol"]
        label   = c["label"]
        try:
            url = (
                f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
                f"?vs_currency=usd&days=365&interval=daily"
            )
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            prices_raw = resp.json()["prices"]  # [[timestamp_ms, price], ...]
            prices = [p[1] for p in prices_raw]

            if len(prices) < 2:
                continue

            closes = prices
            price  = closes[-1]
            d1  = pct_change(price, closes[-2]) if len(closes) >= 2  else None
            d5  = pct_change(price, closes[-6]) if len(closes) >= 6  else None
            d20 = pct_change(price, closes[-21]) if len(closes) >= 21 else None
            d50 = pct_change(price, closes[-51]) if len(closes) >= 51 else None

            sparkline = [round(c, 4) for c in closes[-SPARKLINE_DAYS:]]

            results[label] = {
                "symbol": coin_id,
                "label": label,
                "price": round(price, 2),
                "prev_close": round(closes[-2], 2),
                "change_1d": d1,
                "change_1w": d5,
                "change_20d": d20,
                "change_50d": d50,
                "atr_pct": None,
                "adr_pct": None,
                "dist_52wk_high": round((price - max(closes[-252:])) / max(closes[-252:]) * 100, 2) if len(closes) >= 252 else None,
                "grade": grade(closes),
                "sparkline": sparkline,
                "updated": datetime.now(timezone.utc).isoformat(),
            }
            time.sleep(1.2)  # CoinGecko free tier rate limit
        except Exception as e:
            print(f"  CoinGecko error for {coin_id}: {e}")

    return results


def fetch_fred_fedfunds():
    """Fetches effective federal funds rate from FRED (no API key needed for this series)."""
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")[1:]  # skip header
        lines = [l for l in lines if l.strip()]
        last_two = lines[-2:]
        vals = [float(l.split(",")[1]) for l in last_two]
        price = vals[-1]
        prev  = vals[-2] if len(vals) > 1 else price
        return {
            "symbol": "FEDFUNDS",
            "label": "FEDFUNDS",
            "price": round(price, 4),
            "prev_close": round(prev, 4),
            "change_1d": pct_change(price, prev),
            "change_1w": None,
            "change_20d": None,
            "change_50d": None,
            "atr_pct": None,
            "adr_pct": None,
            "dist_52wk_high": None,
            "grade": "?",
            "sparkline": [round(float(l.split(",")[1]), 4) for l in lines[-SPARKLINE_DAYS:]],
            "updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  FRED FEDFUNDS fetch error: {e}")
        return None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    market = {}

    # Collect all Yahoo Finance symbols across groups (excluding FEDFUNDS and crypto)
    yahoo_instruments = []
    for group in ["indices", "sentiment", "yields", "forex", "commodities"]:
        for inst in CONFIG["instruments"][group]:
            if inst.get("yahoo", False):
                yahoo_instruments.append(inst)

    print(f"Fetching {len(yahoo_instruments)} Yahoo Finance instruments...")
    yahoo_data = fetch_yahoo_group(yahoo_instruments)
    market.update(yahoo_data)

    # FEDFUNDS from FRED
    print("Fetching FEDFUNDS from FRED...")
    ff = fetch_fred_fedfunds()
    if ff:
        market["FEDFUNDS"] = ff

    # Crypto from CoinGecko
    print("Fetching crypto from CoinGecko...")
    crypto_data = fetch_coingecko()
    market.update(crypto_data)

    # ETFs
    etf_symbols = CONFIG["etfs"]
    etf_instruments = [{"symbol": s, "label": s} for s in etf_symbols]
    print(f"Fetching {len(etf_symbols)} ETFs...")
    etf_data = fetch_yahoo_group(etf_instruments)

    # Write outputs
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "instruments": market,
        "etfs": etf_data,
    }

    out_path = os.path.join(DATA_DIR, "market.json")
    with open(out_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
