# Game Radar 🎯

**Autonomous, zero-cost Google Play market scanner and early growth radar for solo indie game developers.**

Game Radar runs 100% locally on Windows 10/11. It scans Google Play game charts across tier-1 Western and Eastern countries, detects newly released games (age &le; 90 days) showing early growth velocity, backfills up to 90 days of review history for instant day-one trend analysis, filters corporate brand saturation, identifies paid traffic soft launches, and ranks game sub-genres by "What to build right now".

---

## Table of Contents
1. [Key Features](#key-features)
2. [Architecture & Libraries](#architecture--libraries)
3. [Setup & Requirements](#setup--requirements)
4. [Execution Modes & Commands](#execution-modes--commands)
5. [Windows Task Scheduling](#windows-task-scheduling)
6. [Configuration Guide](#configuration-guide)
7. [Project File Map](#project-file-map)
8. [Formulas & Methodology](#formulas--methodology)
9. [Decisions & Rationales](#decisions)
10. [Known Limits & Caveats](#known-limits)

---

## 1. Key Features

- **Tier-1 Western & Eastern Chart Scanning**: Tracks Top Free, Top Grossing, Top New Free, and Movers/Shakers across US, GB, DE, CA, AU, FR, JP, KR, TW, and SG across all 18 Google Play game categories.
- **Immediate Day-One Growth (Review Backfill)**: Pulls date-stamped reviews ordered by `Sort.NEWEST` using pagination tokens to construct daily review aggregates without waiting for weeks of daily snapshots.
- **Install Step Smoothing**: Understands that Google's public install counters update in discrete multi-day steps; spreads jumps evenly across the elapsed days and renders flat days as "no update" (dotted lines) instead of drops to zero.
- **Trend Score (0-100)**: Evaluates games based on 7-day install velocity ($V_7$), acceleration ($ACC$), freshness, multi-market coverage, and user review scores.
- **Sub-genre "Build Now" Score (0-100)**: Ranks 41+ specific game niches (such as `sort-puzzle`, `survivor-roguelike`, `idle-clicker`, `tycoon`, `merge`) by Momentum, Breadth, Openness, Search Demand, and Monetization.
- **Brand & Paid Traffic Filter**: Identifies 50+ major publishers and franchises, flags high-budget hyper-casual studios, detects soft-launch footprints, and isolates organic indie opportunities.
- **Permanent SQLite Storage (WAL Mode)**: Never deletes data; snapshots are append-only. Automatically creates daily WAL backups keeping the last 14 days.
- **Multi-Format Intelligence Reports**: Generates responsive offline HTML reports with sortable tables, complete Markdown-style TXT dossiers, and granular CSV files.
- **Offline FastAPI Web Dashboard**: Real-time interactive UI with canvas charts, live worker streaming, manual AppMagic metrics input, and direct analyst inspection links.

---

## 2. Architecture & Libraries

| Feature / Operation | Library / Provider | Preflight Status | Fallback Behavior |
| :--- | :--- | :--- | :--- |
| **App Metadata & Details** | `google-play-scraper` (JoMingyu) v1.2.7 | Confirmed active (all 19 fields verified) | Bucket midpoint estimate if realInstalls missing |
| **Review Pagination (`Sort.NEWEST`)** | `google-play-scraper` (JoMingyu) v1.2.7 | Confirmed active (`at` date + token) | Stops at release date or review cap |
| **Search Autocomplete** | `gplay-scraper` (Mohammedcha) v1.0.6 | Confirmed active (`suggest_analyze`) | Prefix seeds matching fallback |
| **Chart Top Lists & Movers** | `gplay-scraper` (Mohammedcha) v1.0.6 | Confirmed active (`topselling_new_free`, `topgrossing`, `movers_shakers`, `topselling_free`) | Unavailable collections logged and skipped |
| **Keyword Search Presence** | `google-play-scraper` (JoMingyu) v1.2.7 | Confirmed active (`search`) | Search skipped if rate limited |
| **Google Trends (12w Slope)** | `pytrends` v4.9.2 | Confirmed active (10s polite delay) | Gracefully skipped on HTTP 429; demand points redistributed |
| **Local Web Dashboard** | `fastapi` v0.165.0 + `uvicorn` | Confirmed active (offline, vanilla JS/CSS) | Increments port if 8765 is busy |
| **Testing Suite** | `pytest` v9.2.0 | 12/12 unit and integration tests passing | Runs offline via `run.bat selftest` |

*Preflight capabilities are verified live and recorded in `data/capabilities.json`.*

---

## 3. Setup & Requirements

- **Operating System**: Windows 10 or Windows 11 (64-bit).
- **Python**: Python 3.10 or newer (tested with Python 3.14 / 3.11).
- **Zero Configuration**: Double-clicking `run.bat` automatically:
  1. Detects Python in PATH.
  2. Creates the isolated `.venv` virtual environment if absent.
  3. Installs pinned dependencies from `requirements.txt` (only when modified).
  4. Runs preflight capability diagnostics.
  5. Backs up the database.
  6. Executes the pipeline, creates reports, and starts the dashboard.

---

## 4. Execution Modes & Commands

You can run `run.bat` with different arguments or double-click directly:

```bat
:: 1. Standard Interactive Run (Default)
run.bat

:: 2. Full Scan (Unlimited enrich cap, 20,000 reviews/game cap)
run.bat full

:: 3. Daily Headless Run (For scheduled tasks: no browser popup, no pause)
run.bat daily

:: 4. Report Regeneration (Build reports from existing DB without network calls)
run.bat report

:: 5. Dashboard Only (Start web server on 127.0.0.1:8765)
run.bat dashboard

:: 6. Offline Selftest (Runs pytest and builds demo reports from fixtures)
run.bat selftest
```

---

## 5. Windows Task Scheduling

Game Radar includes zero-admin automated task scripts:

- **Register Daily Schedule**: Double-click `schedule_daily.bat`.
  Registers `GameRadarDaily` in Windows Task Scheduler to run `run.bat daily` every day at **03:00 AM**. Runs under the current user account (no administrator prompt required).
- **Remove Schedule**: Double-click `schedule_remove.bat`.
  Deletes the scheduled task cleanly.

*Note: Windows scheduled tasks execute only when the PC is turned on and the user is logged into Windows.*

---

## 6. Configuration Guide

All configuration files live in `config/` and are directly editable:

- **`config/countries.json`**:
  Defines western and eastern market clusters, country weights, and review languages:
  - Western: US (1.0, `en`), GB (0.8, `en`), DE (0.8, `de`), CA (0.7, `en`), AU (0.7, `en`), FR (0.7, `fr`).
  - Eastern: JP (1.0, `ja`), KR (0.9, `ko`), TW (0.6, `zh_TW`), SG (0.4, `en`).
- **`config/settings.json`**:
  Controls `max_age_days` (default 90), `chart_depth` (default 200), `rate_limit_rps` (1.5), review caps, enrich caps, and feature switches (`keywords`, `trends`, `why_growing`).
- **`config/brands.json`**:
  Lists 30+ big publishers, 28+ hyper-casual publishers, and 30+ franchise names matched case-insensitively.
- **`config/subgenres.json`**:
  Maps 41 distinct game niches to keyword lists for automatic multi-tagging and keyword seed harvesting.

---

## 7. Project File Map

```
GameRadar/
├── run.bat                     # One-click Windows runner
├── schedule_daily.bat          # Registers 03:00 daily scheduled task
├── schedule_remove.bat         # Removes Windows scheduled task
├── README.md                   # Complete documentation & decisions
├── requirements.txt            # Pinned tested Python dependencies
├── pytest.ini                  # Pytest test configuration
├── config/
│   ├── settings.json           # Scraping rate limits, caps, and switches
│   ├── countries.json          # Tier-1 countries, weights, languages
│   ├── brands.json             # Corporate publishers & franchises
│   └── subgenres.json          # 41 sub-genre keyword maps
├── radar/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                  # CLI coordinator and pipeline orchestrator
│   ├── db.py                   # SQLite WAL manager and auto-backup engine
│   ├── limiter.py              # Global polite rate limiter (max 1.5 rps)
│   ├── play_client.py          # Unified client for Play Store APIs
│   ├── preflight.py            # Diagnostic capability verifier
│   ├── report.py               # HTML, TXT, and CSV report generator
│   ├── api.py                  # FastAPI dashboard backend
│   └── pipeline/
│       ├── charts.py           # Stage 1: Chart scanning
│       ├── enrich.py           # Stage 2: App metadata enrichment
│       ├── reviews.py          # Stage 3: Review backfilling & day-one growth
│       ├── track.py            # Stage 4: Install step smoothing
│       ├── metrics.py          # Stage 5: Velocity (V7), ACC, coverage
│       ├── brands.py           # Stage 6: Corporate & paid traffic flags
│       ├── subgenres.py        # Stage 7: Sub-genre keyword tagging
│       ├── score.py            # Stage 8: 0-100 Trend Score
│       ├── keywords.py         # Stage 9: Autocomplete & search opportunity
│       ├── trends.py           # Stage 10: Google Trends 12w slope
│       ├── subgenre_score.py   # Build Now Score calculation
│       └── why.py              # Stage 11: Growth drivers & discovery trace
├── web/
│   ├── index.html              # Offline dashboard SPA HTML
│   ├── app.js                  # Vanilla JavaScript client & charts
│   └── style.css               # Dark theme responsive styling
├── data/
│   ├── radar.db                # SQLite WAL database
│   ├── capabilities.json       # Live preflight test results
│   ├── backups/                # Daily SQLite backups (last 14 kept)
│   └── cache/                  # Developer & query cache
├── reports/                    # Generated HTML, TXT, CSV reports
├── logs/                       # Timestamped run logs
└── tests/
    ├── selftest.py             # Selftest runner with demo generator
    ├── test_limiter.py         # Rate limiter and jitter tests
    ├── test_scoring.py         # Percentile and scoring math tests
    ├── test_tracking.py        # Install step smoothing tests
    ├── test_reviews.py         # Daily review aggregation tests
    ├── test_brands_tags.py     # Brand and keyword tagging tests
    ├── test_report.py          # Offline report output tests
    └── test_resume.py          # Interruption & resume tests
```

---

## 8. Formulas & Methodology

### A. Install Step Smoothing (Discrete Jumps)
Google Play install numbers increment in discrete steps every 1 to 3 days. Game Radar never reports a flat day as a collapse to zero:
$$\text{Spread Speed} = \frac{\text{Installs}_{t_2} - \text{Installs}_{t_1}}{t_2 - t_1}$$
Flat days between $t_1$ and $t_2$ inherit this rate and are tagged `has_counter_update = False` (rendered as dotted lines in charts).

### B. Review Proxy Installs (Day-One Growth)
$$\text{est\_installs\_day}(d) = \text{reviews}(d) \times \left( \frac{\text{realInstalls}_{\text{now}}}{\text{total\_reviews\_collected}} \right)$$
*Valid only when backfill status is `COMPLETE`. Marked as `ESTIMATE`.*

### C. Trend Score (0–100)
Ranked inside the current cohort (age $\le 90$ days):
$$\text{Trend Score} = 40 \times \text{pct}(V_7) + 15 \times \text{pct}(ACC) + 15 \times \left(1 - \frac{\text{age}}{90}\right) + 20 \times \text{pct}(\text{Coverage}) + 10 \times \text{clip}\left(\frac{\text{Score} - 3.0}{2.0}, 0, 1\right)$$
- If $ACC$ is missing: component is $0$ and flagged `acc_missing`.
- Rating component requires at least 50 ratings; otherwise $0$.

### D. Sub-genre "Build Now" Score (0–100)
$$\text{Build Now Score} = 35 \times \text{Momentum} + 15 \times \text{Breadth} + 20 \times \text{Openness} + 20 \times \text{Demand} + 10 \times \text{Monetization}$$
- If Keyword Demand and Google Trends are unavailable, the 20 Demand points are redistributed proportionally ($\times 1.25$ multiplier) over the other 4 components, and flagged `DEMAND_MISSING`.

---

## 9. Decisions & Rationales

1. **Native Python Scrapers Over Node Bridge**:
   Preflight verified that `gplay-scraper` natively provides chart collections (`topselling_new_free`, `movers_shakers`, `topgrossing`, `topselling_free`) and search autocomplete (`suggest_analyze`) directly in Python. This eliminates the dependency on Node.js runtime for chart scraping while preserving 100% functionality.
2. **SQLite WAL Mode & Generator Context Manager**:
   To prevent Windows file locking errors (`WinError 32`), database connections use a generator context manager that guarantees `conn.close()` on every query, while retaining WAL performance.
3. **Resumable Batch Commits**:
   Every stage inspects existing entries before executing network calls. If a run is interrupted (Ctrl+C), re-running immediately resumes where it stopped without duplicating rows or re-fetching known data.
4. **Offline Vanilla JavaScript Dashboard**:
   Zero external CDNs or Node build tools are used. Charting is implemented using clean HTML5 Canvas elements with dynamic scaling, ensuring full offline functionality.
5. **Polite Scraping Constraints**:
   Rate limits are strictly capped at 1.5 requests per second with 0.2–0.6s jitter. Any HTTP 429 or 403 triggers an automatic 60s cooldown sleep before retrying.

---

## 10. Known Limits & Caveats

1. **Step-wise Install Counter**: Google Play public install counts increment in delayed steps (often every 24–72 hours). Velocity calculations smooth these jumps across elapsed days, but intraday spikes cannot be observed directly from public counters.
2. **Review Proxy Approximation**: Because review rates vary across cultures and genres, daily install estimates derived from reviews are marked `ESTIMATE`. They illustrate the relative shape and acceleration of growth, not exact audited downloads.
3. **Google Rate Limits & Unofficial Endpoints**: Scraping public Play Store endpoints without API keys is subject to Google IP throttling and web page layout updates. Unofficial scraper endpoints can change over time. If rate limiting occurs, the tool automatically pauses, backs off with exponential delay, and logs the incident in `run_errors`.
4. **Manual AppMagic Integration**: Google does not disclose revenue or exact downloads for competitor games. Game Radar provides dedicated manual fields and direct search links for AppMagic and Meta Ad Library without scraping those services.
