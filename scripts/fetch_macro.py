#!/usr/bin/env python3
"""Fetch macro economic data from FRED and write data/macro.json."""

import csv
import json
import os
import sys
from datetime import date, timedelta
from io import StringIO

import requests

FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
OUT_FILE  = os.path.join(os.path.dirname(__file__), "..", "data", "macro.json")
START     = (date.today() - timedelta(days=760)).strftime("%Y-%m-%d")


def fetch_fred(series_id, start=START):
    url  = f"{FRED_BASE}?id={series_id}&observation_start={start}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    rows = []
    for r in csv.reader(StringIO(resp.text)):
        if r[0] == "DATE" or r[1] == ".":
            continue
        rows.append((r[0], float(r[1])))
    return rows  # list of (date_str, value) sorted oldest→newest


def last_n(rows, n):
    return [{"date": d, "value": round(v, 4)} for d, v in rows[-n:]]


def mom_series(rows, n=3):
    """Return last n MoM % changes from an index series."""
    out = []
    for i in range(max(1, len(rows) - n), len(rows)):
        mom = round((rows[i][1] / rows[i - 1][1] - 1) * 100, 3)
        out.append({"date": rows[i][0], "value": mom})
    return out


def yoy_series(rows, n=3):
    """Return last n YoY % changes from an index series."""
    out = []
    for i in range(max(12, len(rows) - n), len(rows)):
        yoy = round((rows[i][1] / rows[i - 12][1] - 1) * 100, 3)
        out.append({"date": rows[i][0], "value": yoy})
    return out


def nfp_series(rows, n=3):
    """Return last n MoM changes in thousands from PAYEMS."""
    out = []
    for i in range(max(1, len(rows) - n), len(rows)):
        chg = round(rows[i][1] - rows[i - 1][1], 1)
        out.append({"date": rows[i][0], "value": chg})
    return out


def main():
    series = {}
    errors = []

    try:
        cpi = fetch_fred("CPIAUCSL")
        series["CPI_MOM"] = mom_series(cpi)
        series["CPI_YOY"] = yoy_series(cpi)
    except Exception as e:
        errors.append(f"CPIAUCSL: {e}")

    try:
        core = fetch_fred("CPILFESL")
        series["CORE_CPI_MOM"] = mom_series(core)
        series["CORE_CPI_YOY"] = yoy_series(core)
    except Exception as e:
        errors.append(f"CPILFESL: {e}")

    try:
        payems = fetch_fred("PAYEMS")
        series["NFP"] = nfp_series(payems)
    except Exception as e:
        errors.append(f"PAYEMS: {e}")

    try:
        unrate = fetch_fred("UNRATE")
        series["UNRATE"] = last_n(unrate, 3)
    except Exception as e:
        errors.append(f"UNRATE: {e}")

    try:
        icsa = fetch_fred("ICSA")
        series["ICSA"] = last_n(icsa, 5)
    except Exception as e:
        errors.append(f"ICSA: {e}")

    output = {
        "updated": date.today().isoformat(),
        "series":  series,
    }
    if errors:
        output["errors"] = errors

    with open(OUT_FILE, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"Wrote {OUT_FILE} — series: {list(series.keys())}")
    if errors:
        print("Errors:", errors, file=sys.stderr)


if __name__ == "__main__":
    main()
