"""Database management and SQLite WAL connection for Game Radar.
Handles:
- WAL mode initialization
- Backup at start of every run (keeping last 14)
- Safe transactions and batch commits
- Full schema creation and accessors
"""
import contextlib
from datetime import datetime, timezone, timedelta
import glob
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("radar.db")

def get_default_db_path() -> Path:
    env_path = os.environ.get("RADAR_DB_PATH")
    if env_path:
        return Path(env_path)
    return Path("data") / "radar.db"

BACKUPS_DIR = Path("data") / "backups"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    total_requests INTEGER DEFAULT 0,
    total_failures INTEGER DEFAULT 0,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS run_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    target TEXT,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_progress (
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS failed_apps (
    app_id TEXT PRIMARY KEY,
    error_type TEXT NOT NULL,
    error_message TEXT,
    failed_at TEXT NOT NULL,
    cooldown_until TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS apps (
    app_id TEXT PRIMARY KEY,
    title TEXT,
    developer TEXT,
    developer_id TEXT,
    category TEXT,
    genre TEXT,
    genre_id TEXT,
    released TEXT,
    first_seen_date TEXT,
    age_estimated INTEGER DEFAULT 0,
    is_old INTEGER DEFAULT 0,
    price REAL,
    free INTEGER,
    contains_ads INTEGER,
    offers_iap INTEGER,
    url TEXT,
    icon TEXT,
    summary TEXT,
    description TEXT,
    notes TEXT,
    appmagic_revenue_monthly REAL,
    appmagic_downloads_monthly REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS app_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    app_id TEXT NOT NULL,
    date TEXT NOT NULL,
    real_installs INTEGER,
    installs_label TEXT,
    score REAL,
    ratings INTEGER,
    histogram_json TEXT,
    updated INTEGER,
    price REAL,
    contains_ads INTEGER,
    offers_iap INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(app_id, date)
);

CREATE TABLE IF NOT EXISTS chart_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    date TEXT NOT NULL,
    country TEXT NOT NULL,
    category TEXT NOT NULL,
    collection TEXT NOT NULL,
    rank INTEGER NOT NULL,
    app_id TEXT NOT NULL,
    UNIQUE(date, country, category, collection, rank, app_id)
);

CREATE TABLE IF NOT EXISTS review_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id TEXT NOT NULL,
    locale TEXT NOT NULL,
    date TEXT NOT NULL,
    count INTEGER NOT NULL,
    sum_score REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(app_id, locale, date)
);

CREATE TABLE IF NOT EXISTS backfill_meta (
    app_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    token TEXT,
    last_review_date TEXT,
    total_reviews_collected INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS developer_cache (
    developer_id TEXT PRIMARY KEY,
    dev_name TEXT,
    total_installs INTEGER DEFAULT 0,
    game_count INTEGER DEFAULT 0,
    games_json TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keywords (
    keyword TEXT PRIMARY KEY,
    locale TEXT NOT NULL,
    prefix_len INTEGER,
    search_results_json TEXT,
    median_installs REAL,
    brand_share REAL,
    exact_match_titles INTEGER,
    cohort_in_top10 INTEGER,
    opportunity_score REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trends_cache (
    keyword TEXT PRIMARY KEY,
    region TEXT NOT NULL,
    latest_value REAL,
    slope_12w REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cohort_metrics (
    run_id TEXT NOT NULL,
    app_id TEXT NOT NULL,
    date TEXT NOT NULL,
    age_days INTEGER,
    avg_installs_per_day REAL,
    v7 REAL,
    acc REAL,
    velocity_source TEXT,
    coverage_west REAL,
    coverage_east REAL,
    coverage_all REAL,
    ratings_per_1000 REAL,
    confidence TEXT,
    trend_score_west REAL,
    trend_score_east REAL,
    trend_score_all REAL,
    comp_v7 REAL,
    comp_acc REAL,
    comp_freshness REAL,
    comp_coverage REAL,
    comp_rating REAL,
    brand_flags TEXT,
    paid_suspect_reasons TEXT,
    subgenre_tags TEXT,
    why_growing TEXT,
    how_found TEXT,
    PRIMARY KEY (run_id, app_id)
);

CREATE TABLE IF NOT EXISTS subgenre_scores (
    run_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    group_name TEXT NOT NULL,
    build_now_score REAL,
    comp_momentum REAL,
    comp_breadth REAL,
    comp_openness REAL,
    comp_demand REAL,
    comp_monetization REAL,
    evidence_games_json TEXT,
    PRIMARY KEY (run_id, tag, group_name)
);

CREATE INDEX IF NOT EXISTS idx_chart_entries_date ON chart_entries(date);
CREATE INDEX IF NOT EXISTS idx_chart_entries_app ON chart_entries(app_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_app_date ON app_snapshots(app_id, date);
CREATE INDEX IF NOT EXISTS idx_review_daily_app ON review_daily(app_id);
CREATE INDEX IF NOT EXISTS idx_cohort_metrics_run ON cohort_metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_subgenre_scores_run ON subgenre_scores(run_id);
"""

class Database:
    def __init__(self, db_path: Optional[Any] = None):
        if db_path is None:
            self.db_path = get_default_db_path().resolve()
        else:
            self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def backup_database(self, max_keep: int = 14) -> Optional[str]:
        """Copy database to data/backups/radar_YYYY-MM-DD.db and retain last 14."""
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return None
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dest = BACKUPS_DIR / f"radar_{today_str}.db"
        
        # Use SQLite backup API for a safe WAL backup
        with self.get_connection() as src_conn:
            dest_conn = sqlite3.connect(str(dest))
            src_conn.backup(dest_conn)
            dest_conn.close()

        # Prune old backups keeping only last max_keep
        all_backups = sorted(BACKUPS_DIR.glob("radar_*.db"))
        if len(all_backups) > max_keep:
            for old_file in all_backups[:-max_keep]:
                try:
                    old_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to remove old backup {old_file}: {e}")

        return str(dest)

    def record_failed_app(self, app_id: str, error_type: str, error_message: str, cooldown_days: int = 7):
        """Record an app that permanently failed (e.g. 404) with cooldown."""
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        cooldown_until = (now_dt + timedelta(days=cooldown_days)).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO failed_apps (app_id, error_type, error_message, failed_at, cooldown_until)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(app_id) DO UPDATE SET
                   error_type=excluded.error_type,
                   error_message=excluded.error_message,
                   failed_at=excluded.failed_at,
                   cooldown_until=excluded.cooldown_until""",
                (app_id, error_type, error_message, now_iso, cooldown_until)
            )
            conn.commit()

    def get_cooldown_failed_apps(self) -> Set[str]:
        """Return app_ids that are currently in cooldown from failure."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT app_id FROM failed_apps WHERE cooldown_until > ?",
                (now_iso,)
            ).fetchall()
            return {r["app_id"] for r in rows}

    def save_enrich_batch(self, run_id: str, app_updates: List[Tuple], snapshot_inserts: List[Tuple]):
        """Commit batch of app updates and snapshot inserts in a single transaction."""
        with self.get_connection() as conn:
            if app_updates:
                conn.executemany(
                    """UPDATE apps SET
                       title = ?, developer = ?, developer_id = ?, category = ?,
                       genre = ?, genre_id = ?, released = ?, age_estimated = ?,
                       is_old = ?, price = ?, free = ?, contains_ads = ?,
                       offers_iap = ?, url = ?, icon = ?, summary = ?,
                       description = ?, updated_at = ?
                       WHERE app_id = ?""",
                    app_updates
                )
            if snapshot_inserts:
                conn.executemany(
                    """INSERT OR REPLACE INTO app_snapshots
                       (run_id, app_id, date, real_installs, installs_label, score,
                        ratings, histogram_json, updated, price, contains_ads, offers_iap, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    snapshot_inserts
                )
            conn.commit()

    def log_error(self, run_id: str, stage: str, target: Optional[str], error_type: str, error_message: str):
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO run_errors (run_id, stage, target, error_type, error_message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, stage, target or "", error_type, error_message, now_iso)
            )
            conn.commit()

    def set_stage_status(self, run_id: str, stage: str, status: str, details: Optional[Dict] = None):
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO stage_progress (run_id, stage, status, details_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, stage) DO UPDATE SET
                   status=excluded.status, details_json=excluded.details_json, updated_at=excluded.updated_at""",
                (run_id, stage, status, json.dumps(details) if details else None, now_iso)
            )
            conn.commit()

    def get_stage_status(self, run_id: str, stage: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT status, details_json, updated_at FROM stage_progress WHERE run_id = ? AND stage = ?",
                (run_id, stage)
            ).fetchone()
            if row:
                return {
                    "status": row["status"],
                    "details": json.loads(row["details_json"]) if row["details_json"] else {},
                    "updated_at": row["updated_at"]
                }
            return None

    def start_run(self, run_id: str, mode: str):
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, start_time, mode, status) VALUES (?, ?, ?, ?)",
                (run_id, now_iso, mode, "RUNNING")
            )
            conn.commit()

    def finish_run(self, run_id: str, status: str, requests: int, failures: int, summary: Dict):
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute(
                """UPDATE runs SET end_time = ?, status = ?, total_requests = ?, total_failures = ?, summary_json = ?
                   WHERE run_id = ?""",
                (now_iso, status, requests, failures, json.dumps(summary), run_id)
            )
            conn.commit()

    def get_in_progress_run(self) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT * FROM runs WHERE status = 'RUNNING' ORDER BY start_time DESC LIMIT 1"
            ).fetchone()

    def get_latest_completed_run(self) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT * FROM runs WHERE status = 'COMPLETED' AND mode IN ('standard', 'full', 'daily') ORDER BY start_time DESC LIMIT 1"
            ).fetchone()

    def get_days_of_snapshots(self) -> int:
        with self.get_connection() as conn:
            row = conn.execute("SELECT COUNT(DISTINCT date) as cnt FROM app_snapshots").fetchone()
            return row["cnt"] if row else 0

    def get_database_size_bytes(self) -> int:
        if self.db_path.exists():
            return self.db_path.stat().st_size
        return 0
