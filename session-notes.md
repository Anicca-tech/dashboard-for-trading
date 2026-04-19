# Trading Dashboard — Session Notes
**Date:** 2026-04-18
**Session:** Initial build — Step 1 (Sections 1 & 2)

---

## What Was Built

### File Structure
```
trading-dashboard/
├── index.html                          # Full dashboard UI
├── config.json                         # Single config source of truth
├── data/
│   ├── market.json                     # Stub (populated by GitHub Actions)
│   └── naaim.json                      # Stub (populated by GitHub Actions)
├── scripts/
│   ├── fetch_market.py                 # Data fetcher (Yahoo + CoinGecko + FRED)
│   └── fetch_naaim.py                  # NAAIM scraper
└── .github/workflows/
    ├── market_data.yml                 # Cron: every 5 min Mon–Fri 9am–9pm UTC
    └── naaim_data.yml                  # Cron: every Thursday 11pm UTC
```

### config.json
All of the following live here and nowhere else:
- Instrument lists (indices, sentiment, yields, forex, crypto, commodities) with Yahoo symbols and labels
- ETF universe (34 tickers: WGMI, JETS, ITB, SLV, XPH, IBIT, GDX, ARKK, XBI, FFTY, KRE, SMH, SLX, IYT, XLI, XLK, XLRE, XLV, IPO, GLD, ITA, RSP, TAN, LIT, URNM, IGV, CIBR, XLF, URA, HYG, UFO, REMX, OIH, XLE)
- Alert thresholds (indices 1%, ETFs/commodities/crypto 3%, stocks 5%)
- Stock filter parameters (market cap >$1B, price >$7, avg vol >500K, ATR% >3%, ADR% >3%, above 200MA)
- Position sizing defaults (risk 0.3–0.5%, max 0.7%, stop distance 3–6%, default equity $100K)
- Notification times (10:00, 12:30, 15:30 EST)
- NAAIM URL and cache file path
- FRED series mapping for FEDFUNDS

### index.html
- Single-page dark theme, desktop optimised
- Sticky nav with EST clock, market status (OPEN/PRE/CLOSED), last-updated age
- All 6 section slots present; Sections 3–6 are stubs labelled "Coming in Step X"
- Section 1 (Market Overview): full table with label, price, 1D%, 1W%, 20D%, 50D%, ATR%, ADR%, 52wk high distance, 10-day sparkline, Grade
  - Instrument groups in brief-specified order: Indices, Sentiment, Yields, Forex, Crypto, Commodities
  - NAAIM panel below table: current, prior week, quarter average, as-of date
  - Color coding: green/red for moves, amber for within 5% of 52wk high
  - Inverted color logic for VIX, FEDFUNDS, DXY, US10Y, US02Y (down = green)
  - Grade A/B/C computed from EMA10 > EMA21 > SMA50 logic
- Section 2 (Industry ETFs): full table identical column structure, ranked by 1D% descending
  - Top 5 / Bottom 5 chip summary bar at top of section
  - Sector heatmap below table, color intensity scaled to move magnitude (3 tiers each direction)
  - Sparklines on all rows
- All data loaded from `data/market.json` and `data/naaim.json` (static JSON written by GitHub Actions)
- 5-minute auto-refresh polling JSON files
- Stale data warning (amber) if data is older than 15 minutes

### scripts/fetch_market.py
- Batch downloads 1 year of daily OHLCV from Yahoo Finance via `yfinance` for all instruments and ETFs
- Computes: 1D%, 1W%, 20D%, 50D%, ATR% (14-day), ADR% (20-day), 52wk high distance, 10-day sparkline, Grade (EMA10/EMA21/SMA50)
- Fetches BTCUSD and ETHUSD from CoinGecko free API (1.2s rate limit delay)
- Fetches FEDFUNDS effective rate from FRED CSV (no API key required)
- Writes single output: `data/market.json` with keys `updated`, `instruments`, `etfs`
- Yahoo data keyed by Yahoo symbol (e.g. `"NQ=F"`); crypto keyed by label (e.g. `"BTCUSD"`)
- JS handles both key formats via `instruments[sym] || instruments[lbl]` fallback

### scripts/fetch_naaim.py
- Scrapes naaim.org weekly exposure index table using stdlib HTMLParser (no external deps beyond `requests`)
- Parses: current reading, prior week, ~13-week average (quarter avg), date
- Preserves existing cache on parse failure — never overwrites with empty data
- Output: `data/naaim.json`

### GitHub Actions
- `market_data.yml`: triggers every 5 minutes Mon–Fri 09:00–21:00 UTC, commits `data/market.json` with `[skip ci]`
- `naaim_data.yml`: triggers every Thursday 23:00 UTC, commits `data/naaim.json` with `[skip ci]`
- Both use `workflow_dispatch` for manual trigger

---

## Decisions Made

| Decision | Rationale |
|---|---|
| Static JSON architecture (GitHub Actions writes, page reads) | Avoids CORS issues with Yahoo Finance from browser; no backend required |
| 5-minute refresh interval | User confirmed acceptable (vs. truly live) |
| FEDFUNDS from FRED CSV | No API key needed; official source; updated monthly |
| CoinGecko free tier for crypto | No API key needed; sufficient for daily-ish polling |
| NAAIM stdlib parser, no BeautifulSoup | Minimises dependencies; simpler GitHub Actions setup |
| Inverted color for VIX, DXY, US10Y, US02Y, FEDFUNDS | Lower = better for market — green on down moves |
| Amber 52wk high distance threshold: within 5% | Flags proximity to resistance; configurable in future |
| `[skip ci]` on data commits | Prevents infinite GitHub Actions loop |
| Sections 3–6 stubbed as placeholders | Build each in isolation per brief sequence |

---

## Decisions from Pre-Build Brief

| Topic | Decision |
|---|---|
| X API / sector scanner | **Discarded from v1.0** — no X developer account |
| Outlook email delivery | **Discarded from v1.0** — dashboard notifications only |
| Pre-filtered stock universe for notifications | **Confirmed** — nightly screener builds candidate universe, intraday only checks thresholds against it |
| GitHub Actions cron jitter (1–2 min) | **Confirmed acceptable** |
| Portfolio section | **Deferred to v2.0** — Dropbox API OAuth complexity |
| Mobile app | **Deferred to later phase** |

---

## Constraints and Open Issues

### 1. Yahoo Finance Breadth Indicators — VERIFY BEFORE LAUNCH
The following sentiment symbols may not be available via yfinance (they are StockCharts proprietary):
- `^MMFI` (% NYSE stocks above 50MA)
- `^MMTH` (% NYSE stocks above 200MA)
- `^NYAD` used as proxy for NCFD — confirm this is the right symbol
- `^SKEW` used for SKFD — this is the CBOE SKEW Index, verify Mario's intent

**Action required:** Run `fetch_market.py` once and check which of these return data. If empty, identify alternative sources (StockCharts does not have a public API; Barchart or alternative may be needed, or these fields show "—" permanently).

### 2. US02Y Symbol
Using `^IRX` (13-week T-bill) as a proxy for the 2-year yield. This is not accurate — the 2-year yield is a different instrument.
**Action required:** Confirm whether `^IRX` is acceptable or if Mario wants the true 2-year. FRED series `DGS2` gives the 2-year daily — could add to `fetch_market.py` alongside FEDFUNDS at no extra cost.

### 3. Python Not Available in Local Shell
`fetch_market.py` and `fetch_naaim.py` can only be tested via GitHub Actions (Linux runner). Local validation requires Python + yfinance installed.
**Action required:** To test locally, install Python and run `pip install yfinance requests` then `python scripts/fetch_market.py`.

### 4. NAAIM Page Structure
Parser written against current naaim.org table structure (Date | Members | Average | High | Low | Median). If the page changes, the scraper returns nothing and preserves the cache.
**Action required:** Manually trigger `naaim_data.yml` via workflow_dispatch after pushing to GitHub and verify output.

### 5. GitHub Pages Setup
Dashboard is built as a static site but no `gh-pages` branch or Pages configuration has been set up yet.
**Action required:** Create GitHub repo → push → Settings → Pages → deploy from `main` branch root.

---

## Exact Next Steps to Continue

### Immediate (before Step 2)
1. **Create GitHub repository** for this project
2. **Push all files** to `main` branch
3. **Enable GitHub Pages** — Settings → Pages → Source: `main` / `/ (root)`
4. **Trigger `market_data.yml` manually** via Actions → workflow_dispatch — wait for it to complete and commit `data/market.json`
5. **Open the live GitHub Pages URL** in browser
6. **Verify each instrument group** loads with data — note any symbols returning "—"
7. **Report back** which of `^MMFI`, `^MMTH`, `^NYAD`, `^SKEW` return data vs. are empty
8. **Decide on US02Y** — `^IRX` proxy or FRED `DGS2`
9. **Trigger `naaim_data.yml` manually** — verify NAAIM panel populates (or report parse failure)

### Step 2 (next code session)
Build **Section 4 — Position Sizing Calculator** in full isolation:
- Account equity, risk %, entry price, stop price, optional ticker
- Outputs: shares, max risk USD, position value, risk per share, % equity at risk
- 2-stop and 3-stop modes with scale-out visualization
- Long and short support
- R:R targets
- All defaults pre-loaded from `config.json` (risk 0.4%, stop 3–6%, equity $100K)

### Step 3
Build **Section 3 — Watchlist** (depends on Yahoo Finance feed from Step 1)

### Step 4
Build **Section 5 — Calendar and Economic Events**

### Step 5
Build **Section 6 — Intelligence** (after-hours movers + IPO briefing; sector scanner discarded)

### Step 6
Build **Intraday Notifications** (dashboard alert panels; email delivery discarded from v1.0)

---

## Tech Stack Summary
- **Frontend:** HTML/CSS/JS, no framework, single file
- **Data pipeline:** Python (yfinance, requests), runs in GitHub Actions
- **Scheduling:** GitHub Actions cron
- **Market data:** Yahoo Finance (yfinance) + CoinGecko free API + FRED CSV
- **Hosting:** GitHub Pages (static)
- **Config:** `config.json` — single source of truth, never hardcode parameters in core files
