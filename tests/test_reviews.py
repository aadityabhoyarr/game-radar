import os
import tempfile
from radar.db import Database
from radar.pipeline.metrics import compute_daily_review_estimates

def test_daily_review_estimates():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_path = tf.name

    try:
        db = Database(temp_path)
        app_id = "com.test.reviewgame"

        # Insert daily review aggregates
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO review_daily (app_id, locale, date, count, sum_score, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (app_id, "en-US", "2026-11-20", 50, 220.0, "2026-11-21T00:00:00")
            )
            conn.execute(
                "INSERT INTO review_daily (app_id, locale, date, count, sum_score, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (app_id, "en-US", "2026-11-19", 30, 130.0, "2026-11-21T00:00:00")
            )
            conn.commit()

        # Real installs = 100,000, Total reviews collected = 800
        # Multiplier = 100,000 / 800 = 125.0
        estimates = compute_daily_review_estimates(db, app_id, real_installs=100000, total_reviews_collected=800)
        assert estimates["2026-11-20"] == 50 * 125.0 # 6250.0
        assert estimates["2026-11-19"] == 30 * 125.0 # 3750.0
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
