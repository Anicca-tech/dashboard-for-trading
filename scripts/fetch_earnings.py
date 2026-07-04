#!/usr/bin/env python3
"""
Fetch earnings calendar from the Nasdaq public API and write data/earnings.json.
Entries are pre-normalized to the shape calLoadEarnings() expects in index.html.

Covers: 1 week back, current week, 2 weeks forward (4 weeks × 5 days).

No API key or crumb required. The Nasdaq API requires origin/referer headers
that identify the request as coming from nasdaq.com — without them it 403s.
"""

import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import requests

ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE  = os.path.join(ROOT, "data", "earnings.json")

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin":          "https://www.nasdaq.com",
    "Referer":         "https://www.nasdaq.com/market-activity/earnings",
}

TIME_MAP = {
    "time-before-hours": "BMO",
    "time-after-hours":  "AMC",
}


def week_dates(offset_weeks=0):
    today  = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset_weeks)
    return [(monday + timedelta(days=i)).isoformat() for i in range(5)]


def _parse_float(val):
    """Return float or None from a string that may be empty, 'N/A', or whitespace."""
    if val is None:
        return None
    s = str(val).strip()
    if not s or s in ("N/A", "—", "-"):
        return None
    try:
        return float(s.replace(",", "").replace("%", ""))
    except ValueError:
        return None


def fetch_day(date_str):
    url = f"https://api.nasdaq.com/api/calendar/earnings?date={date_str}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        body = resp.json()
        rows = (body.get("data") or {}).get("rows") or []

        if not rows:
            snippet = json.dumps(body)[:300]
            print(f"  {date_str}: 0 entries — response: {snippet}")
            return []

        entries = []
        for r in rows:
            ticker = (r.get("symbol") or "").strip().upper()
            if not ticker:
                continue
            entries.append({
                "ticker":   ticker,
                "company":  (r.get("name") or "—").strip(),
                "date":     date_str,
                "type":     TIME_MAP.get(r.get("time") or "", ""),
                "epsEst":   _parse_float(r.get("eps_forecast")),
                "epsAct":   None,   # Nasdaq calendar does not expose post-report actuals
                "surprise": _parse_float(r.get("epssurprisepct")),
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
            time.sleep(0.3)

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
