"""
Scrapes NAAIM Exposure Index from naaim.org and writes to data/naaim.json.
Run by GitHub Actions every Thursday after 6pm EST.
"""

import json
import os
import re
from datetime import datetime, timezone
import requests
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
OUT_PATH = os.path.join(DATA_DIR, "naaim.json")
URL = "https://www.naaim.org/programs/naaim-exposure-index/"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_td = False
        self.rows = []
        self.current_row = []
        self.current_cell = ""

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
        if self.in_table and tag == "tr":
            self.current_row = []
        if self.in_table and tag in ("td", "th"):
            self.in_td = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
        if self.in_table and tag in ("td", "th"):
            self.current_row.append(self.current_cell.strip())
            self.in_td = False
        if self.in_table and tag == "tr" and self.current_row:
            self.rows.append(self.current_row)
            self.current_row = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data


def parse_float(s):
    try:
        return round(float(re.sub(r"[^\d.\-]", "", s)), 2)
    except (ValueError, TypeError):
        return None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load existing cache so we don't lose data on parse failure
    existing = {}
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH) as f:
                existing = json.load(f)
        except Exception:
            pass

    try:
        resp = requests.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to fetch NAAIM page: {e}")
        # Preserve existing cache
        if existing:
            print("Preserving existing cache.")
        return

    parser = TableParser()
    parser.feed(resp.text)

    # Find the data rows — NAAIM table typically has: Date | Members Reporting | Average | High | Low | Median
    data_rows = []
    for row in parser.rows:
        if len(row) >= 3 and re.match(r"\d{1,2}/\d{1,2}/\d{4}", row[0]):
            data_rows.append(row)

    if not data_rows:
        print("Could not parse NAAIM table — structure may have changed. Preserving cache.")
        return

    # Most recent is first row after sorting descending by date
    readings = []
    for row in data_rows[:14]:  # ~1 quarter of weekly readings
        try:
            date_str = row[0].strip()
            exposure = parse_float(row[2]) if len(row) > 2 else None
            if exposure is not None:
                readings.append({"date": date_str, "exposure": exposure})
        except Exception:
            continue

    if not readings:
        print("No readable NAAIM readings found. Preserving cache.")
        return

    current  = readings[0]["exposure"] if len(readings) >= 1 else None
    prior    = readings[1]["exposure"] if len(readings) >= 2 else None
    q_avg    = round(sum(r["exposure"] for r in readings[:13]) / min(len(readings), 13), 2)

    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "current": current,
        "current_date": readings[0]["date"] if readings else None,
        "prior": prior,
        "prior_date": readings[1]["date"] if len(readings) >= 2 else None,
        "quarter_avg": q_avg,
        "history": readings,
    }

    with open(OUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"NAAIM data written: current={current}, prior={prior}, q_avg={q_avg}")


if __name__ == "__main__":
    main()
