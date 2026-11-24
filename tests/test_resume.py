import os
import tempfile
from radar.db import Database
from radar.pipeline.enrich import get_prioritized_candidates

def test_resume_and_skip_old_apps():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_path = tf.name

    try:
        db = Database(temp_path)
        run_id = "run_resume_test"

        with db.get_connection() as conn:
            # Game 1: young game
            conn.execute(
                "INSERT INTO apps (app_id, title, released, is_old) VALUES (?, ?, ?, ?)",
                ("com.young.game", "Young Game", "2026-11-01", 0)
            )
            # Game 2: old game (is_old = 1)
            conn.execute(
                "INSERT INTO apps (app_id, title, released, is_old) VALUES (?, ?, ?, ?)",
                ("com.old.game", "Old Game", "2024-01-01", 1)
            )
            # Both appear in chart entries
            conn.execute(
                "INSERT INTO chart_entries (run_id, date, country, category, collection, rank, app_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, "2026-11-21", "US", "GAME", "topselling_new_free", 1, "com.young.game")
            )
            conn.execute(
                "INSERT INTO chart_entries (run_id, date, country, category, collection, rank, app_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, "2026-11-21", "US", "GAME", "topselling_new_free", 2, "com.old.game")
            )
            conn.commit()

        candidates = get_prioritized_candidates(db, run_id, max_age_days=90)
        # Old game MUST be skipped
        assert "com.young.game" in candidates
        assert "com.old.game" not in candidates
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
