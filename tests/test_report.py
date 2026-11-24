import json
import os
import tempfile
from radar.db import Database
from radar.report import generate_reports

def test_report_generation_offline():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_path = tf.name

    output_dir = tempfile.mkdtemp()

    try:
        db = Database(temp_path)
        run_id = "run_demo_fixture"
        today_str = "2026-11-21"

        db.start_run(run_id, "standard")

        with db.get_connection() as conn:
            # Insert demo app
            conn.execute(
                """INSERT INTO apps (app_id, title, developer, category, released, first_seen_date, url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("com.fixture.puzzle", "Fixture Puzzle Jam", "Indie Craftsman", "GAME_PUZZLE", "2026-11-05", "2026-11-05", "https://play.google.com/store/apps/details?id=com.fixture.puzzle")
            )
            # Insert snapshot
            conn.execute(
                """INSERT INTO app_snapshots (run_id, app_id, date, real_installs, score, ratings, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, "com.fixture.puzzle", today_str, 25000, 4.6, 210, "2026-11-21T10:00:00")
            )
            # Insert chart entry
            conn.execute(
                """INSERT INTO chart_entries (run_id, date, country, category, collection, rank, app_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, today_str, "US", "GAME_PUZZLE", "topselling_new_free", 4, "com.fixture.puzzle")
            )
            # Insert cohort metric
            conn.execute(
                """INSERT INTO cohort_metrics
                   (run_id, app_id, date, age_days, avg_installs_per_day, v7, acc, velocity_source,
                    coverage_west, coverage_east, coverage_all, ratings_per_1000, confidence,
                    trend_score_west, trend_score_east, trend_score_all,
                    comp_v7, comp_acc, comp_freshness, comp_coverage, comp_rating,
                    brand_flags, paid_suspect_reasons, subgenre_tags, why_growing, how_found)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, "com.fixture.puzzle", today_str, 16, 1562.5, 2100.0, 1.25, "reviews_proxy",
                    8.5, 4.0, 12.5, 8.4, "MEDIUM",
                    82.5, 78.0, 85.0,
                    36.0, 12.0, 12.3, 17.5, 8.0,
                    json.dumps({"big_publisher": False, "hypercasual_publisher": False, "franchise": False, "paid_traffic_suspect": False, "hidden_by_default": False}),
                    "[]", json.dumps(["sort-puzzle", "match-3"]),
                    json.dumps({"drivers": [{"label": "ESTIMATE", "driver": "Chart-driven", "evidence": "Rank #4 in US"}], "how_found": "2026-11-05 US topselling_new_free #4"}),
                    "2026-11-05 US topselling_new_free #4"
                )
            )
            # Insert subgenre score
            conn.execute(
                """INSERT INTO subgenre_scores
                   (run_id, tag, group_name, build_now_score, comp_momentum, comp_breadth,
                    comp_openness, comp_demand, comp_monetization, evidence_games_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, "sort-puzzle", "all", 88.0, 32.0, 14.0, 20.0, 15.0, 7.0,
                    json.dumps([{"app_id": "com.fixture.puzzle", "title": "Fixture Puzzle Jam", "trend_score": 85.0}])
                )
            )
            conn.commit()

        db.finish_run(run_id, "COMPLETED", 10, 0, {"summary": "demo"})

        reports = generate_reports(db, run_id, output_dir=output_dir)

        # Assert report files exist
        assert os.path.exists(reports["html"])
        assert os.path.exists(reports["txt"])
        assert os.path.exists(reports["csv"])
        assert os.path.exists(reports["latest_html"])
        assert os.path.exists(reports["latest_txt"])
        assert os.path.exists(reports["latest_csv"])

        # Check TXT report contents
        with open(reports["txt"], "r", encoding="utf-8") as f:
            txt_content = f.read()

        assert "Fixture Puzzle Jam" in txt_content
        assert "com.fixture.puzzle" in txt_content
        assert "A. RUN HEADER" in txt_content
        assert "B. FUNNEL" in txt_content
        assert "C. SHORTLIST NAMES" in txt_content
        assert "D. FULL COHORT GAME TABLE" in txt_content
        assert "E. DETAIL FOR TOP 30 GAMES" in txt_content
        assert "F. SUB-GENRE RANKINGS" in txt_content
        assert "I. VERIFY BLOCK" in txt_content
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
