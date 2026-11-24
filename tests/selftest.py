"""Self-test runner for Game Radar.
Runs pytest offline and generates demo reports in reports/demo_*.html, .txt, .csv.
"""
from datetime import datetime, timezone
import json
import os
import sys
import pytest

from radar.db import Database
from radar.report import generate_reports

def build_demo_fixture_report(db: Database, output_dir: str = "reports") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    today_dt = datetime.now(timezone.utc)
    today_date = today_dt.strftime("%Y-%m-%d")
    ts_str = today_dt.strftime("%Y-%m-%d_%H%M")
    run_id = f"demo_{ts_str}"

    db.start_run(run_id, "selftest_demo")

    demo_games = [
        {
            "app_id": "com.indie.roomsort3d",
            "title": "Room Sort 3D: Cozy Clean",
            "developer": "Alpenhof Indie Studio",
            "category": "GAME_PUZZLE",
            "released": "2026-10-25",
            "age_days": 27,
            "real_installs": 250000,
            "installs_label": "100,000+",
            "score": 4.7,
            "ratings": 1850,
            "v7": 6200.0,
            "acc": 1.45,
            "tags": ["sort-puzzle", "satisfying-asmr"],
            "drivers": [
                {"label": "ESTIMATE", "driver": "Chart-driven", "evidence": "Ranks #1 in US TOP_NEW_FREE"},
                {"label": "ESTIMATE", "driver": "Wave", "evidence": "4 cohort games in sort-puzzle released within 30 days"}
            ],
            "how_found": "2026-10-26 US topselling_new_free #1",
            "trend_score": 92.4,
            "is_clean": True
        },
        {
            "app_id": "com.indie.pixelbullet",
            "title": "Survivor Pixel Legion",
            "developer": "Solo Tiny Dev",
            "category": "GAME_ACTION",
            "released": "2026-11-02",
            "age_days": 19,
            "real_installs": 120000,
            "installs_label": "100,000+",
            "score": 4.6,
            "ratings": 940,
            "v7": 4100.0,
            "acc": 1.30,
            "tags": ["survivor-roguelike", "idle-rpg"],
            "drivers": [
                {"label": "ESTIMATE", "driver": "Search-driven", "evidence": "Ranks in top 10 for 'bullet heaven'"},
                {"label": "ESTIMATE", "driver": "Chart-driven", "evidence": "Ranks #3 in JP topselling_new_free"}
            ],
            "how_found": "2026-11-03 JP topselling_new_free #3",
            "trend_score": 88.6,
            "is_clean": True
        },
        {
            "app_id": "com.voodoo.runner3d",
            "title": "Count Crowd Runner 3D",
            "developer": "Voodoo",
            "category": "GAME_ARCADE",
            "released": "2026-11-10",
            "age_days": 11,
            "real_installs": 500000,
            "installs_label": "500,000+",
            "score": 3.9,
            "ratings": 210,
            "v7": 12000.0,
            "acc": 0.90,
            "tags": ["hyper-casual-runner"],
            "drivers": [
                {"label": "ESTIMATE", "driver": "Paid-traffic signs", "evidence": "Known hyper-casual publisher, low ratings per install"}
            ],
            "how_found": "2026-11-11 US topselling_free #5",
            "trend_score": 84.1,
            "is_clean": False, # Hypercasual publisher
            "flags": {"hypercasual_publisher": True, "hidden_by_default": True, "paid_traffic_suspect": True}
        }
    ]

    with db.get_connection() as conn:
        for g in demo_games:
            aid = g["app_id"]
            flags = g.get("flags") or {"big_publisher": False, "hypercasual_publisher": False, "franchise": False, "paid_traffic_suspect": False, "hidden_by_default": not g["is_clean"]}
            
            # Apps table
            conn.execute(
                """INSERT OR REPLACE INTO apps (app_id, title, developer, category, released, first_seen_date, url, contains_ads, offers_iap)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (aid, g["title"], g["developer"], g["category"], g["released"], g["released"], f"https://play.google.com/store/apps/details?id={aid}", 1, 1)
            )

            # Snapshot
            conn.execute(
                """INSERT OR REPLACE INTO app_snapshots (run_id, app_id, date, real_installs, installs_label, score, ratings, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, aid, today_date, g["real_installs"], g["installs_label"], g["score"], g["ratings"], today_dt.isoformat())
            )

            # Chart entry
            conn.execute(
                """INSERT OR REPLACE INTO chart_entries (run_id, date, country, category, collection, rank, app_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, today_date, "US", g["category"], "topselling_new_free", 1, aid)
            )

            # Reviews daily
            conn.execute(
                """INSERT OR REPLACE INTO review_daily (app_id, locale, date, count, sum_score, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (aid, "en-US", today_date, 45, 200.0, today_dt.isoformat())
            )

            # Backfill meta
            conn.execute(
                """INSERT OR REPLACE INTO backfill_meta (app_id, status, token, last_review_date, total_reviews_collected, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (aid, "COMPLETE", "token_sample", today_date, 500, today_dt.isoformat())
            )

            # Cohort metrics
            conn.execute(
                """INSERT OR REPLACE INTO cohort_metrics
                   (run_id, app_id, date, age_days, avg_installs_per_day, v7, acc, velocity_source,
                    coverage_west, coverage_east, coverage_all, ratings_per_1000, confidence,
                    trend_score_west, trend_score_east, trend_score_all,
                    comp_v7, comp_acc, comp_freshness, comp_coverage, comp_rating,
                    brand_flags, paid_suspect_reasons, subgenre_tags, why_growing, how_found)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, aid, today_date, g["age_days"], g["real_installs"] / g["age_days"],
                    g["v7"], g["acc"], "reviews_proxy",
                    8.0, 7.0, 15.0, (g["ratings"] / g["real_installs"]) * 1000, "MEDIUM",
                    g["trend_score"], g["trend_score"] - 2, g["trend_score"],
                    36.0, 12.0, 12.0, 16.0, 8.0,
                    json.dumps(flags), json.dumps(g.get("flags", {}).get("paid_suspect_reasons", [])),
                    json.dumps(g["tags"]), json.dumps({"drivers": g["drivers"], "how_found": g["how_found"]}),
                    g["how_found"]
                )
            )

        # Subgenre score
        conn.execute(
            """INSERT OR REPLACE INTO subgenre_scores
               (run_id, tag, group_name, build_now_score, comp_momentum, comp_breadth,
                comp_openness, comp_demand, comp_monetization, evidence_games_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, "sort-puzzle", "all", 89.5, 32.5, 14.0, 20.0, 15.0, 8.0,
                json.dumps([{"app_id": "com.indie.roomsort3d", "title": "Room Sort 3D: Cozy Clean", "trend_score": 92.4}])
            )
        )
        conn.commit()

    db.finish_run(run_id, "COMPLETED", 5, 0, {"demo": True})

    reports = generate_reports(db, run_id, output_dir=output_dir, make_latest=False)

    # Copy to demo_YYYY-MM-DD_HHMM
    demo_html = os.path.join(output_dir, f"demo_{ts_str}.html")
    demo_txt = os.path.join(output_dir, f"demo_{ts_str}.txt")
    demo_csv = os.path.join(output_dir, f"demo_{ts_str}.csv")

    import shutil
    shutil.copy(reports["html"], demo_html)
    shutil.copy(reports["txt"], demo_txt)
    shutil.copy(reports["csv"], demo_csv)

    return {
        "html": demo_html,
        "txt": demo_txt,
        "csv": demo_csv
    }

def run_selftest():
    import tempfile
    print("=================================================================")
    print("                RUNNING GAME RADAR SELFTEST SUITE                ")
    print("=================================================================")

    # 1. Run pytest
    print("[1/2] Running automated unit and integration tests via pytest...")
    ret_code = pytest.main(["-v", "tests"])
    if ret_code != 0:
        print(f"[!] Pytest reported test failures (exit code: {ret_code})")
        sys.exit(ret_code)
    print("[+] All unit and integration tests PASSED!")

    # 2. Build demo report from fixtures into reports/demo_* using isolated DB
    print("\n[2/2] Building demo market report from fixtures into reports/...")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        demo_db = Database(temp_db_path)
        demo_paths = build_demo_fixture_report(demo_db, "reports")
        print(f"[+] Demo reports successfully generated:")
        print(f"    - HTML: {demo_paths['html']}")
        print(f"    - TXT:  {demo_paths['txt']}")
        print(f"    - CSV:  {demo_paths['csv']}")
    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass
    print("\n=================================================================")
    print("                    SELFTEST PASSED (100%)                       ")
    print("=================================================================")

if __name__ == "__main__":
    run_selftest()
