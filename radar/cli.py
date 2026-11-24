"""CLI entrypoint and execution coordinator for Game Radar.
Handles commands:
- run (--mode standard | full | daily)
- report (regenerate report from DB only)
- dashboard (start FastAPI server)
- selftest (offline verification)
"""
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("radar.cli")

from radar.db import Database
from radar.limiter import RateLimiter, set_limiter
from radar.play_client import PlayClient
from radar.preflight import run_preflight
from radar.pipeline.charts import run_stage_charts
from radar.pipeline.enrich import run_stage_enrich
from radar.pipeline.reviews import run_stage_reviews
from radar.pipeline.track import run_stage_track
from radar.pipeline.metrics import run_stage_metrics
from radar.pipeline.brands import run_stage_brands
from radar.pipeline.subgenres import run_stage_subgenres
from radar.pipeline.score import run_stage_score
from radar.pipeline.keywords import run_stage_keywords
from radar.pipeline.trends import run_stage_trends
from radar.pipeline.subgenre_score import compute_build_now_scores
from radar.pipeline.why import run_stage_why
from radar.report import generate_reports

def setup_logging(log_filename: Optional[str] = None):
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    if not log_filename:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
        log_path = logs_dir / f"run_{ts}.log"
    else:
        log_path = Path(log_filename)
        log_path.parent.mkdir(parents=True, exist_ok=True)
    
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
    file_handler.setFormatter(formatter)
    
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [file_handler, stream_handler]

def load_json_config(path: Any) -> dict:
    p = Path(path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def run_pipeline(
    mode: str = "standard",
    log_file: Optional[str] = None,
    enrich_cap: Optional[int] = None,
    all_candidates: bool = False,
    force_enrich: bool = False,
    enrich_workers: Optional[int] = None,
    db_path: Optional[str] = None
):
    if db_path:
        os.environ["RADAR_DB_PATH"] = str(Path(db_path).resolve())

    setup_logging(log_file)
    print("=================================================================")
    print("                     GAME RADAR (VERSION 1.0.0)                  ")
    print("=================================================================")
    print(f"Mode: {mode.upper()} | Start: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    db = Database(db_path)

    # Step 0: Backup DB
    backup_file = db.backup_database(max_keep=14)
    if backup_file:
        print(f"[BACKUP] Database backed up to {backup_file}")

    # Load configs
    countries_cfg = load_json_config("config/countries.json")
    settings_cfg = load_json_config("config/settings.json")
    brands_cfg = load_json_config("config/brands.json")
    subgenres_cfg = load_json_config("config/subgenres.json")

    # Rate limiter setup
    limiter = RateLimiter(
        max_rps=settings_cfg.get("rate_limit_rps", 1.5),
        jitter_min=settings_cfg.get("jitter_min", 0.2),
        jitter_max=settings_cfg.get("jitter_max", 0.6),
        max_retries=settings_cfg.get("max_retries", 5),
        cooldown_seconds=settings_cfg.get("cooldown_seconds", 60.0),
        proxies=settings_cfg.get("proxies", [])
    )
    set_limiter(limiter)
    client = PlayClient()

    # Preflight capabilities check
    cap_path = "data/capabilities.json"
    if not os.path.exists(cap_path):
        capabilities = run_preflight(cap_path)
    else:
        with open(cap_path, "r", encoding="utf-8") as f:
            capabilities = json.load(f)

    print(f"[PREFLIGHT] Google Play Scraper: {capabilities.get('google_play_scraper', {}).get('version')} (App fields: {capabilities.get('google_play_scraper', {}).get('app_fields_confirmed')})")
    print(f"[PREFLIGHT] GPlay Scraper: {capabilities.get('gplay_scraper', {}).get('version')} (Max count: {capabilities.get('gplay_scraper', {}).get('max_count')})")
    print(f"[PREFLIGHT] PyTrends: {capabilities.get('pytrends', {}).get('version')} (Live: {capabilities.get('pytrends', {}).get('works')})")

    # Start run or resume in-progress run
    in_progress = db.get_in_progress_run()
    if in_progress:
        run_id = in_progress["run_id"]
        if mode == "standard" and not all_candidates and enrich_cap is None:
            mode = in_progress["mode"]
        print(f"[RESUME] Found interrupted run {run_id} ({mode} mode). Resuming...")
    else:
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        db.start_run(run_id, mode)

    try:
        # Stage 1: CHARTS
        st1 = db.get_stage_status(run_id, "CHARTS")
        if st1 and st1.get("status") == "COMPLETED":
            print(f"[CHARTS] Stage already COMPLETED for {run_id}. Skipping.")
            stage1_res = st1.get("details", {})
        else:
            stage1_res = run_stage_charts(db, client, run_id, countries_cfg, settings_cfg, mode=mode)

        # Stage 2: ENRICH
        st2 = db.get_stage_status(run_id, "ENRICH")
        if st2 and st2.get("status") == "COMPLETED":
            print(f"[ENRICH] Stage already COMPLETED for {run_id}. Skipping.")
            stage2_res = st2.get("details", {})
        else:
            stage2_res = run_stage_enrich(
                db, client, run_id, settings_cfg,
                countries_config=countries_cfg,
                mode=mode,
                enrich_cap=enrich_cap,
                all_candidates=all_candidates,
                force_enrich=force_enrich,
                enrich_workers=enrich_workers
            )

        # Stage 3: REVIEWS BACKFILL
        st3 = db.get_stage_status(run_id, "REVIEWS")
        if st3 and st3.get("status") == "COMPLETED":
            print(f"[REVIEWS] Stage already COMPLETED for {run_id}. Skipping.")
            stage3_res = st3.get("details", {})
        else:
            stage3_res = run_stage_reviews(db, client, run_id, countries_cfg, settings_cfg, mode=mode)

        # Stage 4: TRACK
        stage4_res = run_stage_track(db, run_id)

        # Stage 5: METRICS
        cohort_metrics = run_stage_metrics(db, run_id, countries_cfg, settings_cfg)

        # Stage 6: BRANDS
        dev_pages_enabled = settings_cfg.get("feature_switches", {}).get("developer_pages", True)
        brand_flags = run_stage_brands(db, run_id, brands_cfg, cohort_metrics, client=client if dev_pages_enabled else None)

        # Stage 7: SUBGENRE TAGS
        cohort_aids = list(cohort_metrics.keys())
        game_tags = run_stage_subgenres(db, run_id, subgenres_cfg, cohort_aids)

        # Stage 8: TREND SCORE
        game_scores = run_stage_score(db, run_id, cohort_metrics)

        # Stage 9: KEYWORDS
        top_momentum_tags = list(subgenres_cfg.keys())[:10]
        switches = settings_cfg.get("feature_switches", {})
        kw_results = []
        if switches.get("keywords", True):
            st_kw = db.get_stage_status(run_id, "KEYWORDS")
            if st_kw and st_kw.get("status") == "COMPLETED":
                print(f"[KEYWORDS] Stage already COMPLETED for {run_id}. Loading from DB...")
                with db.get_connection() as conn:
                    rows = conn.execute("SELECT * FROM keywords ORDER BY opportunity_score DESC").fetchall()
                    kw_results = [dict(r) for r in rows]
            else:
                kw_results = run_stage_keywords(db, client, run_id, top_momentum_tags, subgenres_cfg, brands_cfg, set(cohort_aids))

        # Stage 10: TRENDS
        trends_results = {}
        if switches.get("trends", True) and kw_results:
            st_tr = db.get_stage_status(run_id, "TRENDS")
            if st_tr and st_tr.get("status") in ("COMPLETED", "SKIPPED"):
                print(f"[TRENDS] Stage already COMPLETED for {run_id}. Loading from DB...")
                with db.get_connection() as conn:
                    rows = conn.execute("SELECT * FROM trends_cache").fetchall()
                    trends_results = {r["keyword"]: dict(r) for r in rows}
            else:
                trend_keywords = [k["keyword"] for k in kw_results[:10]]
                trends_results = run_stage_trends(db, run_id, trend_keywords, region="US", max_keywords=10)

        # Subgenre Build Now Score
        subgenre_scores = compute_build_now_scores(
            db, run_id, subgenres_cfg, game_tags, game_scores, brand_flags,
            cohort_metrics, kw_results, trends_results
        )

        # Stage 11: WHY GROWING
        # Top 30 clean games
        clean_top30 = sorted(
            [aid for aid in cohort_aids if not brand_flags.get(aid, {}).get("hidden_by_default")],
            key=lambda aid: game_scores.get(aid, {}).get("trend_score_all", 0.0),
            reverse=True
        )[:30]
        why_results = {}
        if switches.get("why_growing", True):
            why_results = run_stage_why(db, run_id, clean_top30, cohort_metrics, game_scores, brand_flags, game_tags)

        # Persist full cohort metrics to database
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with db.get_connection() as conn:
            for aid in cohort_aids:
                m = cohort_metrics.get(aid, {})
                s = game_scores.get(aid, {})
                b = brand_flags.get(aid, {})
                tags = game_tags.get(aid, [])
                w = why_results.get(aid, {})

                conn.execute(
                    """INSERT OR REPLACE INTO cohort_metrics
                       (run_id, app_id, date, age_days, avg_installs_per_day, v7, acc, velocity_source,
                        coverage_west, coverage_east, coverage_all, ratings_per_1000, confidence,
                        trend_score_west, trend_score_east, trend_score_all,
                        comp_v7, comp_acc, comp_freshness, comp_coverage, comp_rating,
                        brand_flags, paid_suspect_reasons, subgenre_tags, why_growing, how_found)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, aid, today_date, m.get("age_days"), m.get("avg_installs_per_day"),
                        m.get("v7"), m.get("acc"), m.get("velocity_source"),
                        m.get("coverage_west"), m.get("coverage_east"), m.get("coverage_all"),
                        m.get("ratings_per_1000"), m.get("confidence"),
                        s.get("trend_score_west"), s.get("trend_score_east"), s.get("trend_score_all"),
                        s.get("comp_v7"), s.get("comp_acc"), s.get("comp_freshness"),
                        s.get("comp_coverage_all"), s.get("comp_rating"),
                        json.dumps(b), json.dumps(b.get("paid_suspect_reasons", [])),
                        json.dumps(tags), json.dumps(w), w.get("how_found")
                    )
                )
            conn.commit()

        # Finish run in DB
        with db.get_connection() as conn:
            actual_failures = conn.execute("SELECT COUNT(*) as c FROM run_errors WHERE run_id = ?", (run_id,)).fetchone()["c"]
        summary = {
            "cohort_count": len(cohort_aids),
            "charts_summary": stage1_res,
            "enrich_summary": stage2_res,
            "reviews_summary": stage3_res
        }
        total_reqs = limiter.request_count
        if total_reqs == 0:
            ch_req = stage1_res.get("total_targets", 0)
            en_req = stage2_res.get("processed", 0)
            rv_req = stage3_res.get("total_reviews", 0) // 200
            total_reqs = ch_req + en_req + rv_req + len(kw_results) + len(trends_results)
        db.finish_run(run_id, "COMPLETED", total_reqs, actual_failures, summary)

        # Stage 12: REPORT
        reports = generate_reports(db, run_id, output_dir="reports")
        print("=================================================================")
        print("                        RUN COMPLETED                            ")
        print("=================================================================")
        print(f"HTML Report:   {reports['html']}")
        print(f"TXT Report:    {reports['txt']}")
        print(f"CSV Report:    {reports['csv']}")
        print(f"Total Requests: {limiter.request_count} | Total Failures: {limiter.failure_count}")
        return run_id, reports

    except Exception as e:
        logger.exception(f"Pipeline crashed in run {run_id}: {e}")
        db.finish_run(run_id, "FAILED", limiter.request_count, limiter.failure_count, {"error": str(e)})
        raise e

def run_report_only(db_path: Optional[str] = None):
    """Regenerates report from latest completed run in DB."""
    if db_path:
        os.environ["RADAR_DB_PATH"] = str(Path(db_path).resolve())
    db = Database(db_path)
    latest = db.get_latest_completed_run()
    if not latest:
        print("[REPORT] No completed runs found in database. Run the pipeline first.")
        return
    run_id = latest["run_id"]
    print(f"[REPORT] Regenerating report for run {run_id}...")
    reports = generate_reports(db, run_id, output_dir="reports")
    print(f"[REPORT] Reports generated:")
    print(f"  {reports['html']}")
    print(f"  {reports['txt']}")
    print(f"  {reports['csv']}")

def main():
    parser = argparse.ArgumentParser(description="Game Radar - Automated Market Intelligence")
    subparsers = parser.add_subparsers(dest="command")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run the radar pipeline")
    run_parser.add_argument("--mode", default="standard", choices=["standard", "full", "daily"], help="Execution mode")
    run_parser.add_argument("--log-file", default=None, help="Path to write log output")
    run_parser.add_argument("--enrich-cap", type=int, default=None, help="Max candidates to enrich (0 = unlimited)")
    run_parser.add_argument("--all-candidates", action="store_true", help="Shortcut for unlimited candidate enrichment")
    run_parser.add_argument("--force-enrich", action="store_true", help="Force re-enrichment of apps even within freshness window")
    run_parser.add_argument("--enrich-workers", type=int, default=None, help="Concurrent workers for enrichment (default from settings)")
    run_parser.add_argument("--db-path", default=None, help="Path to SQLite database file (overrides RADAR_DB_PATH)")

    # Report command
    report_parser = subparsers.add_parser("report", help="Regenerate reports from existing database")
    report_parser.add_argument("--db-path", default=None, help="Path to SQLite database file (overrides RADAR_DB_PATH)")

    # Dashboard command
    dash_parser = subparsers.add_parser("dashboard", help="Start FastAPI dashboard")
    dash_parser.add_argument("--port", type=int, default=8765, help="Port to run dashboard")
    dash_parser.add_argument("--db-path", default=None, help="Path to SQLite database file (overrides RADAR_DB_PATH)")

    # Selftest command
    selftest_parser = subparsers.add_parser("selftest", help="Run test suite and build demo reports")
    selftest_parser.add_argument("--db-path", default=None, help="Path to SQLite database file (overrides RADAR_DB_PATH)")

    args = parser.parse_args()

    if args.command == "run":
        cap_val = 0 if args.all_candidates else args.enrich_cap
        run_pipeline(
            mode=args.mode,
            log_file=args.log_file,
            enrich_cap=cap_val,
            all_candidates=args.all_candidates,
            force_enrich=args.force_enrich,
            enrich_workers=args.enrich_workers,
            db_path=args.db_path
        )
    elif args.command == "report":
        run_report_only(db_path=args.db_path)
    elif args.command == "dashboard":
        if args.db_path:
            os.environ["RADAR_DB_PATH"] = str(Path(args.db_path).resolve())
        from radar.api import start_dashboard
        start_dashboard(port=args.port)
    elif args.command == "selftest":
        if args.db_path:
            os.environ["RADAR_DB_PATH"] = str(Path(args.db_path).resolve())
        from tests.selftest import run_selftest
        run_selftest()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
