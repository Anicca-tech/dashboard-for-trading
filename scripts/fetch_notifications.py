"""
fetch_notifications.py
Runs at 10:05, 12:35, 15:35 ET Mon–Fri (three crons in one workflow).
Determines slot (n1/n2/n3) from wall-clock ET time.
Updates data/notifications.json in-place — other slots are preserved.

n1  10:00 AM — market open scan
n2  12:30 PM — midday scan + sector rotation vs n1
n3   3:30 PM — pre-close scan + index day-range table
"""

import json
import os
import sys
import requests
import yfinance as yf
from datetime import datetime
import pytz

# ── Config ───────────────────────────────────────────────────────────────────

with open('config.json') as f:
    CONFIG = json.load(f)

NOTIF   = CONFIG['notifications']
THR     = NOTIF['thresholds']
ETF_TKS = CONFIG['etfs']                         # list of 34 ETF tickers

ET = pytz.timezone('America/New_York')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; dashboard-bot/1.0)',
    'Accept': 'application/json',
}

# Build label maps once from config
_IDX_LABELS = {d['symbol']: d['label']
               for grp in CONFIG['instruments'].values()
               for d in (grp if isinstance(grp, list) else [])
               if isinstance(d, dict) and 'symbol' in d}

WATCH_INDICES    = NOTIF.get('watch_indices',    ['^GSPC', '^IXIC', '^DJI', 'IWM', 'RTY=F'])
WATCH_COMMODITIES = NOTIF.get('watch_commodities', [
    {'symbol': 'GC=F',  'label': 'Gold',   'threshold': THR.get('gold_move_pct',   2.0)},
    {'symbol': 'SI=F',  'label': 'Silver', 'threshold': THR.get('silver_move_pct', 2.0)},
    {'symbol': 'CL=F',  'label': 'WTI',    'threshold': THR.get('wti_move_pct',    2.0)},
    {'symbol': 'BZ=F',  'label': 'Brent',  'threshold': THR.get('brent_move_pct',  2.0)},
])
WATCH_CRYPTO = NOTIF.get('watch_crypto', [
    {'symbol': 'BTC-USD', 'label': 'BTC', 'threshold': THR.get('bitcoin_move_pct',  3.0)},
    {'symbol': 'ETH-USD', 'label': 'ETH', 'threshold': THR.get('ethereum_move_pct', 3.0)},
])


# ── Yahoo Finance batch quote ─────────────────────────────────────────────────

def yf_quotes(symbols: list) -> dict:
    """Fetch quotes for any number of symbols, batched at 50. Returns {symbol: quote}."""
    out = {}
    for i in range(0, len(symbols), 50):
        batch = symbols[i:i + 50]
        url = ('https://query2.finance.yahoo.com/v7/finance/quote?symbols='
               + ','.join(batch))
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            for q in r.json().get('quoteResponse', {}).get('result', []):
                out[q['symbol']] = q
        except Exception as e:
            print(f'quote batch error: {e}', file=sys.stderr)
    return out


# ── Stock screener ────────────────────────────────────────────────────────────

def screen_stocks() -> list:
    """Return US stocks with big intraday moves passing all configured filters."""
    min_move  = THR['stock_move_pct']
    min_cap   = THR['stock_min_market_cap']
    min_price = THR['stock_min_price']
    min_vol   = THR['stock_min_avg_volume']
    min_atr   = THR['stock_min_atr_pct']
    min_adr   = THR['stock_min_adr_pct']

    raw = []
    for scr in ('day_gainers', 'day_losers'):
        try:
            url = (
                'https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved'
                f'?formatted=false&lang=en-US&region=US&scrIds={scr}&count=50'
            )
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            result = r.json()['finance']['result']
            if result:
                raw.extend(result[0].get('quotes', []))
        except Exception as e:
            print(f'screener {scr}: {e}', file=sys.stderr)

    seen, candidates = set(), []
    for q in raw:
        sym = q.get('symbol', '')
        if sym in seen:
            continue
        seen.add(sym)
        pct     = q.get('regularMarketChangePercent', 0) or 0
        price   = q.get('regularMarketPrice', 0) or 0
        mkt_cap = q.get('marketCap', 0) or 0
        vol3m   = q.get('averageDailyVolume3Month', 0) or 0
        ma200   = q.get('twoHundredDayAverage', 0) or 0
        exch    = q.get('exchange', '')

        if abs(pct)   < min_move:  continue
        if price      < min_price: continue
        if mkt_cap    < min_cap:   continue
        if vol3m      < min_vol:   continue
        if ma200 and price < ma200: continue          # must be above 200 MA
        if exch not in ('NYQ', 'NMS', 'NGM', 'NCM', 'ASE', 'NYSEArca', ''):
            if q.get('quoteType') not in ('EQUITY', None):
                continue
        candidates.append({
            'symbol':   sym,
            'name':     q.get('shortName', sym),
            'pct':      round(pct, 2),
            'price':    round(price, 2),
            'mkt_cap':  mkt_cap,
        })

    # Compute ATR14% and ADR20% from history; skip if below thresholds
    results = []
    for c in candidates:
        try:
            hist = yf.Ticker(c['symbol']).history(period='25d')
            if len(hist) < 14:
                continue
            h  = hist['High']
            l  = hist['Low']
            pc = hist['Close'].shift(1)
            tr = (h - l).combine(abs(h - pc), max).combine(abs(l - pc), max)
            last_close = hist['Close'].iloc[-1]
            atr_pct = (tr.rolling(14).mean().iloc[-1] / last_close) * 100
            adr_pct = ((hist['High'] - hist['Low']) / hist['Low']).tail(20).mean() * 100
            if atr_pct < min_atr or adr_pct < min_adr:
                continue
            c['atr_pct'] = round(float(atr_pct), 2)
            c['adr_pct'] = round(float(adr_pct), 2)
            results.append(c)
        except Exception as e:
            print(f'ATR/ADR {c["symbol"]}: {e}', file=sys.stderr)

    results.sort(key=lambda x: abs(x['pct']), reverse=True)
    return results


# ── Alert builder ─────────────────────────────────────────────────────────────

def build_alerts(quotes: dict) -> list:
    alerts = []

    # Indices
    thr_idx = THR['indices_move_pct']
    for sym in WATCH_INDICES:
        q = quotes.get(sym)
        if not q:
            continue
        pct = q.get('regularMarketChangePercent', 0) or 0
        if abs(pct) >= thr_idx:
            alerts.append({
                'type':   'index',
                'ticker': sym,
                'label':  _IDX_LABELS.get(sym, sym),
                'pct':    round(pct, 2),
                'price':  round(q.get('regularMarketPrice', 0), 2),
            })

    # ETFs
    thr_etf = THR['etf_move_pct']
    for sym in ETF_TKS:
        q = quotes.get(sym)
        if not q:
            continue
        pct = q.get('regularMarketChangePercent', 0) or 0
        if abs(pct) >= thr_etf:
            alerts.append({
                'type':   'etf',
                'ticker': sym,
                'label':  sym,
                'pct':    round(pct, 2),
                'price':  round(q.get('regularMarketPrice', 0), 2),
            })

    # Commodities (individual thresholds)
    for c in WATCH_COMMODITIES:
        q = quotes.get(c['symbol'])
        if not q:
            continue
        pct = q.get('regularMarketChangePercent', 0) or 0
        thr = float(c.get('threshold', 2.0))
        if abs(pct) >= thr:
            alerts.append({
                'type':   'commodity',
                'ticker': c['symbol'],
                'label':  c['label'],
                'pct':    round(pct, 2),
                'price':  round(q.get('regularMarketPrice', 0), 2),
            })

    # Crypto (individual thresholds)
    for c in WATCH_CRYPTO:
        q = quotes.get(c['symbol'])
        if not q:
            continue
        pct = q.get('regularMarketChangePercent', 0) or 0
        thr = float(c.get('threshold', 3.0))
        if abs(pct) >= thr:
            alerts.append({
                'type':   'crypto',
                'ticker': c['symbol'],
                'label':  c['label'],
                'pct':    round(pct, 2),
                'price':  round(q.get('regularMarketPrice', 0), 2),
            })

    # Individual stocks
    for s in screen_stocks():
        alerts.append({'type': 'stock', 'ticker': s['symbol'], 'label': s['symbol'], **s})

    return alerts


# ── ETF ranking ───────────────────────────────────────────────────────────────

def etf_ranking(quotes: dict):
    ranked = sorted(
        [{'ticker': sym,
          'pct': round((quotes[sym].get('regularMarketChangePercent', 0) or 0), 2)}
         for sym in ETF_TKS if sym in quotes],
        key=lambda x: x['pct'], reverse=True,
    )
    top5    = [r['ticker'] for r in ranked[:5]]
    bottom5 = [r['ticker'] for r in ranked[-5:]]
    return top5, bottom5, ranked


# ── Sector rotation ───────────────────────────────────────────────────────────

def sector_rotation(prev_top5, prev_bot5, cur_top5, cur_bot5, ranked) -> list:
    pct_map = {r['ticker']: r['pct'] for r in ranked}
    events = []
    for t in prev_top5:
        if t in cur_bot5:
            events.append({'ticker': t, 'was': 'top5', 'now': 'bottom5',
                           'pct_now': pct_map.get(t, 0)})
    for t in prev_bot5:
        if t in cur_top5:
            events.append({'ticker': t, 'was': 'bottom5', 'now': 'top5',
                           'pct_now': pct_map.get(t, 0)})
    return events


# ── Index day range (N3) ──────────────────────────────────────────────────────

def indices_range(quotes: dict) -> list:
    result = []
    for sym in WATCH_INDICES:
        q = quotes.get(sym)
        if not q:
            continue
        high    = q.get('regularMarketDayHigh', 0) or 0
        low     = q.get('regularMarketDayLow',  0) or 0
        current = q.get('regularMarketPrice',   0) or 0
        pct     = q.get('regularMarketChangePercent', 0) or 0
        range_pct = round((current - low) / (high - low) * 100, 1) if high > low else None
        result.append({
            'ticker':    sym,
            'label':     _IDX_LABELS.get(sym, sym),
            'high':      round(high, 2),
            'low':       round(low, 2),
            'current':   round(current, 2),
            'pct':       round(pct, 2),
            'range_pct': range_pct,
        })
    return result


# ── Slot determination ────────────────────────────────────────────────────────

def determine_slot(now_et: datetime) -> str:
    h = now_et.hour
    # 5-minute window around each target hour
    if 9 <= h <= 10:
        return 'n1'
    elif 11 <= h <= 12:
        return 'n2'
    else:
        return 'n3'


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)
    slot   = determine_slot(now_et)
    today  = now_et.strftime('%Y-%m-%d')
    print(f'slot={slot}  time={now_et.strftime("%H:%M ET")}')

    all_syms = (
        WATCH_INDICES
        + ETF_TKS
        + [c['symbol'] for c in WATCH_COMMODITIES]
        + [c['symbol'] for c in WATCH_CRYPTO]
    )
    quotes = yf_quotes(all_syms)

    alerts = build_alerts(quotes)
    top5, bottom5, ranked = etf_ranking(quotes)

    # Load existing file — preserve other slots, reset if different day
    data_path = 'data/notifications.json'
    existing  = {}
    if os.path.exists(data_path):
        try:
            with open(data_path) as f:
                existing = json.load(f)
            if existing.get('date') != today:
                existing = {}
        except Exception:
            existing = {}

    slot_data = {
        'slot':        slot,
        'time_label':  {'n1': '10:00 AM ET', 'n2': '12:30 PM ET', 'n3': '3:30 PM ET'}[slot],
        'triggered_at': now_et.isoformat(),
        'alert_count': len(alerts),
        'alerts':      alerts,
        'etf_top5':    top5,
        'etf_bottom5': bottom5,
    }

    if slot == 'n2':
        prev = existing.get('n1', {})
        rot  = sector_rotation(
            prev.get('etf_top5',    []),
            prev.get('etf_bottom5', []),
            top5, bottom5, ranked,
        )
        slot_data['sector_rotation'] = rot

    if slot == 'n3':
        slot_data['indices_range'] = indices_range(quotes)

    existing.update({'date': today, 'updated_at': now_et.isoformat(), slot: slot_data})

    os.makedirs('data', exist_ok=True)
    with open(data_path, 'w') as f:
        json.dump(existing, f, indent=2)

    print(f'wrote {len(alerts)} alerts → data/notifications.json')


if __name__ == '__main__':
    main()
