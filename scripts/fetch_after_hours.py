import json
import os
import requests
from datetime import datetime
import pytz

with open('config.json') as f:
    cfg = json.load(f)['intelligence']['after_hours']

MIN_MOVE    = cfg['min_move_pct']        # 6.0
MIN_CAP     = cfg['min_market_cap']      # 1_000_000_000
MIN_PRICE   = cfg['min_price']           # 7.0
MAX_RESULTS = cfg['max_results']         # 10
REQUIRE_CAT = cfg.get('require_catalyst', True)

ET = pytz.timezone('America/New_York')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; dashboard-bot/1.0)',
    'Accept': 'application/json',
}


def screener(scr_id: str) -> list:
    url = (
        'https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved'
        f'?formatted=false&lang=en-US&region=US&scrIds={scr_id}&count=50'
    )
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    result = r.json()['finance']['result']
    return result[0].get('quotes', []) if result else []


def get_catalyst(ticker: str, since_ts: float) -> str | None:
    """Return first headline published after since_ts, or None."""
    url = (
        f'https://query1.finance.yahoo.com/v1/finance/search'
        f'?q={ticker}&newsCount=5&quotesCount=0'
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        for n in r.json().get('news', []):
            if n.get('providerPublishTime', 0) >= since_ts:
                title = n.get('title', '')
                return title[:90] if title else None
        return None
    except Exception:
        return None


def earnings_today(q: dict, now_et: datetime) -> str | None:
    ts = q.get('earningsTimestamp')
    if not ts:
        return None
    dt = datetime.fromtimestamp(ts, tz=ET)
    if dt.date() == now_et.date() and dt.hour >= 16:
        return f"Earnings AH ({dt.strftime('%b %d')})"
    return None


def main():
    now_et   = datetime.now(ET)
    cutoff   = now_et.replace(hour=16, minute=0, second=0, microsecond=0).timestamp()

    quotes = []
    for scr in ('after_hours_gainer', 'after_hours_loser'):
        try:
            quotes.extend(screener(scr))
        except Exception as e:
            print(f'screener {scr}: {e}')

    # Deduplicate
    seen, unique = set(), []
    for q in quotes:
        sym = q.get('symbol', '')
        if sym and sym not in seen:
            seen.add(sym)
            unique.append(q)

    results = []
    for q in unique:
        ah_pct  = q.get('postMarketChangePercent', 0) or 0
        price   = q.get('regularMarketPrice', 0) or 0
        mkt_cap = q.get('marketCap', 0) or 0
        ticker  = q.get('symbol', '')
        exch    = q.get('exchange', '')

        if abs(ah_pct) < MIN_MOVE:   continue
        if price   < MIN_PRICE:       continue
        if mkt_cap < MIN_CAP:         continue
        # US-listed only
        if exch not in ('NYQ', 'NMS', 'NGM', 'NCM', 'ASE', 'NYSEArca', ''):
            if q.get('quoteType') not in ('EQUITY', None):
                continue

        catalyst = earnings_today(q, now_et) or get_catalyst(ticker, cutoff)
        if REQUIRE_CAT and not catalyst:
            continue

        results.append({
            'ticker':    ticker,
            'name':      q.get('shortName', ticker),
            'ah_pct':    round(ah_pct, 2),
            'ah_price':  round(q.get('postMarketPrice', price), 2),
            'reg_price': round(price, 2),
            'mkt_cap':   mkt_cap,
            'volume':    q.get('regularMarketVolume', 0),
            'catalyst':  catalyst or 'Post-market move',
        })

    results.sort(key=lambda x: abs(x['ah_pct']), reverse=True)
    results = results[:MAX_RESULTS]

    os.makedirs('data', exist_ok=True)
    with open('data/after_hours.json', 'w') as f:
        json.dump({
            'generated_at': now_et.isoformat(),
            'as_of':        now_et.strftime('%b %d, %Y %I:%M %p ET'),
            'count':        len(results),
            'movers':       results,
        }, f, indent=2)
    print(f'after_hours: {len(results)} movers written')


if __name__ == '__main__':
    main()
