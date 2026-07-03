#!/usr/bin/env python3
"""
Fetch earnings calendar from Yahoo Finance for a rolling window of weeks
and write data/earnings.json. Entries are pre-normalized to the shape
calLoadEarnings() expects in index.html, so no client-side transform is needed.

Covers: 1 week back, current week, 2 weeks forward (4 weeks × 5 days).
"""

import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE   = os.path.join(ROOT, "data", "earnings.json")
CONFIG     = json.load(open(os.path.join(ROOT, "config.json")))
PAGE_SIZE  = CONFIG.get("calendar", {}).get("earnings_per_day", 50)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}


def week_dates(offset_weeks=0):
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset_weeks)
    return [(monday + timedelta(days=i)).isoformat() for i in range(5)]


def _val(entry, *keys):
    for k in keys:
        v = entry.get(k)
        if v is not None:
            return v
    return None


def fetch_day(date_str):
    url = (
        f"https://query2.finance.yahoo.com/v1/finance/earnings"
        f"?date={date_str}&size={PAGE_SIZE}&offset=0"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        raw = (
            resp.json()
            .get("earnings", {})
            .get("result", {})
            .get("earningsDate", [])
        )
        entries = []
        for e in raw:
            ticker = (_val(e, "ticker", "symbol") or "").upper()
            if not ticker:
                continue
            entries.append({
                "ticker":   ticker,
                "company":  _val(e, "companyshortname", "longName") or "—",
                "date":     date_str,
                "type":     e.get("startdatetimetype") or "",
                "epsEst":   _val(e, "epsestimate",    "epsEstimate"),
                "epsAct":   _val(e, "epsactual",      "epsActual"),
                "surprise": _val(e, "surprisepercent", "surprisePercent"),
            })
        return entries
    except Exception as exc:
        print(f"  {date_str}: error — {exc}")
        return []


def main():
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    weeks = {}

    # -1 = last week, 0 = this week, +1 = next week, +2 = week after
    for offset in range(-1, 3):
        for d in week_dates(offset):
            entries = fetch_day(d)
            print(f"  {d}: {len(entries)} entries")
            if entries:
                weeks[d] = entries
            time.sleep(0.4)   # stay well within Yahoo rate limits

    total = sum(len(v) for v in weeks.values())
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "weeks":   weeks,
    }
    with open(OUT_FILE, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"Wrote {OUT_FILE} — {len(weeks)} days, {total} entries")


if __name__ == "__main__":
    main()
