import json
import os
import requests
import yfinance as yf
from datetime import datetime, timedelta
import pytz

with open('config.json') as f:
    cfg = json.load(f)['intelligence']['ipo_briefing']

RECENT_MONTHS = cfg['recent_ipo_months']       # 6
WK_THRESHOLD  = cfg['weekly_move_threshold']   # 10.0
MAX_FILINGS   = cfg['max_filings']             # 20
MAX_PRICED    = cfg['max_priced']              # 10
MAX_DELAYED   = cfg['max_delayed']             # 10
MAX_MOVERS    = cfg['max_weekly_movers']        # 20

ET = pytz.timezone('America/New_York')

SEC_HEADERS = {
    'User-Agent': 'IPO-Tracker marius.muellerhoff@outlook.de',
    'Accept': 'application/json',
}


def sec_search(forms: list[str], days_back: int = 7) -> list:
    end   = datetime.now()
    start = end - timedelta(days=days_back)
    url = (
        'https://efts.sec.gov/LATEST/search-index?q='
        f'&forms={",".join(forms)}'
        f'&dateRange=custom'
        f'&startdt={start.strftime("%Y-%m-%d")}'
        f'&enddt={end.strftime("%Y-%m-%d")}'
        '&hits.hits.total.value=true'
    )
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=25)
        r.raise_for_status()
        return r.json().get('hits', {}).get('hits', [])
    except Exception as e:
        print(f'SEC search {forms}: {e}')
        return []


def parse_hit(h: dict) -> dict:
    src = h.get('_source', {})
    return {
        'company': src.get('entity_name', 'Unknown'),
        'ticker':  src.get('ticker', ''),
        'form':    src.get('form_type', ''),
        'filed':   src.get('file_date', ''),
    }


def weekly_change(ticker: str) -> float | None:
    try:
        hist = yf.Ticker(ticker).history(period='5d')
        if len(hist) >= 2:
            return round(((hist['Close'].iloc[-1] / hist['Close'].iloc[0]) - 1) * 100, 2)
    except Exception:
        pass
    return None


def current_price(ticker: str) -> float | None:
    try:
        p = yf.Ticker(ticker).fast_info.last_price
        return round(p, 2) if p else None
    except Exception:
        return None


def get_sector(ticker: str) -> str:
    try:
        return yf.Ticker(ticker).info.get('sector', 'Unknown')
    except Exception:
        return 'Unknown'


def main():
    now_et = datetime.now(ET)

    # 1. New S-1 / F-1 filings this week
    new_filings, seen_f = [], set()
    for h in sec_search(['S-1', 'F-1'], days_back=7):
        rec = parse_hit(h)
        key = f"{rec['company']}_{rec['form']}"
        if key not in seen_f:
            seen_f.add(key)
            new_filings.append({'company': rec['company'], 'ticker': rec['ticker'],
                                'form': rec['form'], 'filed': rec['filed']})
    new_filings = new_filings[:MAX_FILINGS]

    # 2. Recently priced (424B4 = final prospectus)
    recently_priced, seen_p = [], set()
    for h in sec_search(['424B4'], days_back=7):
        rec = parse_hit(h)
        if rec['company'] in seen_p:
            continue
        seen_p.add(rec['company'])
        entry = {'company': rec['company'], 'ticker': rec['ticker'], 'priced_date': rec['filed']}
        if rec['ticker']:
            p = current_price(rec['ticker'])
            if p:
                entry['current_price'] = p
        recently_priced.append(entry)
    recently_priced = recently_priced[:MAX_PRICED]

    # 3. Delayed / Withdrawn (RW = withdrawal request; S-1/A or F-1/A = amended/delayed)
    delayed, seen_d = [], set()
    for h in sec_search(['RW', 'S-1/A', 'F-1/A'], days_back=14):
        rec = parse_hit(h)
        if rec['company'] in seen_d:
            continue
        seen_d.add(rec['company'])
        status = 'Withdrawn' if rec['form'] == 'RW' else 'Amended/Delayed'
        delayed.append({'company': rec['company'], 'form': rec['form'],
                        'status': status, 'filed': rec['filed']})
    delayed = delayed[:MAX_DELAYED]

    # 4. Recent IPOs (<N months) with weekly move > threshold
    weekly_movers, seen_m = [], set()
    for h in sec_search(['424B4'], days_back=RECENT_MONTHS * 30):
        rec = parse_hit(h)
        t = rec['ticker']
        if not t or t in seen_m:
            continue
        seen_m.add(t)
        wk = weekly_change(t)
        if wk is None or abs(wk) < WK_THRESHOLD:
            continue
        weekly_movers.append({
            'ticker': t, 'name': rec['company'],
            'ipo_date': rec['filed'], 'weekly_chg': wk,
            'price': current_price(t),
        })
    weekly_movers.sort(key=lambda x: abs(x['weekly_chg']), reverse=True)
    weekly_movers = weekly_movers[:MAX_MOVERS]

    # 5. Sector trends
    sector_map: dict[str, dict] = {}
    for entry in recently_priced + weekly_movers:
        t = entry.get('ticker', '')
        if not t:
            continue
        sec = get_sector(t)
        if sec not in sector_map:
            sector_map[sec] = {'count': 0, 'total_chg': 0.0}
        sector_map[sec]['count'] += 1
        sector_map[sec]['total_chg'] += entry.get('weekly_chg', 0)
    sector_trends = sorted([
        {'sector': s, 'count': v['count'],
         'avg_weekly_chg': round(v['total_chg'] / v['count'], 2)}
        for s, v in sector_map.items()
    ], key=lambda x: x['count'], reverse=True)

    os.makedirs('data', exist_ok=True)
    with open('data/ipo_briefing.json', 'w') as f:
        json.dump({
            'generated_at':    now_et.isoformat(),
            'week_of':         now_et.strftime('Week of %B %d, %Y'),
            'new_filings':     new_filings,
            'recently_priced': recently_priced,
            'delayed_withdrawn': delayed,
            'weekly_movers':   weekly_movers,
            'sector_trends':   sector_trends,
        }, f, indent=2)
    print(f'ipo_briefing: {len(new_filings)} filings, {len(recently_priced)} priced, {len(weekly_movers)} movers')


if __name__ == '__main__':
    main()
