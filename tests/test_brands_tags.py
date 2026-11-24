import os
import tempfile
from radar.db import Database
from radar.pipeline.brands import match_brand_names, run_stage_brands
from radar.pipeline.subgenres import tag_game_text

def test_brand_matching():
    big_pubs = ["Supercell", "Electronic Arts", "Tencent"]
    assert match_brand_names("supercell", big_pubs) is True
    assert match_brand_names("ELECTRONIC ARTS INC.", big_pubs) is True
    assert match_brand_names("Indie Solo Dev", big_pubs) is False

    franchises = ["Candy Crush", "Pokemon", "Clash of Clans"]
    assert match_brand_names("Candy Crush Soda Saga", franchises) is True
    assert match_brand_names("Pocket Monster Adventure", franchises) is False

def test_subgenre_tagging():
    subgenres = {
        "merge": ["merge", "combine"],
        "sort-puzzle": ["water sort", "color sort", "sort puzzle"],
        "tycoon": ["tycoon", "supermarket simulator"]
    }
    # Matches sort-puzzle
    t1 = tag_game_text("Color Sort 3D - Fun Water Sort Game", subgenres, "GAME_PUZZLE")
    assert "sort-puzzle" in t1

    # Fallback to category id
    t2 = tag_game_text("Random Unrelated Space Adventure", subgenres, "GAME_ACTION")
    assert t2 == ["GAME_ACTION"]

def test_paid_traffic_and_studio_flags():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_path = tf.name

    try:
        db = Database(temp_path)
        run_id = "run_test_brands"

        with db.get_connection() as conn:
            # Big dev with 50M+ installs
            conn.execute(
                "INSERT INTO apps (app_id, title, developer, category, released) VALUES (?, ?, ?, ?, ?)",
                ("com.mega.game", "Mega Block Blast", "MegaStudio", "GAME_PUZZLE", "2026-11-01")
            )
            conn.execute(
                "INSERT INTO app_snapshots (run_id, app_id, date, real_installs, score, ratings, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, "com.mega.game", "2026-11-20", 60000000, 4.5, 500, "2026-11-20")
            )
            # Suspicious game: 100k installs, but only 5 ratings -> ratings_per_1000 = 0.05
            conn.execute(
                "INSERT INTO apps (app_id, title, developer, category, released) VALUES (?, ?, ?, ?, ?)",
                ("com.paid.game", "Crazy Fast Runner", "Unknown Dev", "GAME_ACTION", "2026-11-15")
            )
            conn.execute(
                "INSERT INTO app_snapshots (run_id, app_id, date, real_installs, score, ratings, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, "com.paid.game", "2026-11-20", 100000, 4.0, 5, "2026-11-20")
            )
            conn.commit()

        brands_cfg = {
            "big_publishers": ["Supercell"],
            "hypercasual_publishers": ["Voodoo"],
            "franchises": ["Roblox"]
        }
        cohort_metrics = {
            "com.mega.game": {"age_days": 20, "ratings_per_1000": 8.3},
            "com.paid.game": {"age_days": 5, "ratings_per_1000": 0.05}
        }

        flags = run_stage_brands(db, run_id, brands_cfg, cohort_metrics)
        assert flags["com.mega.game"]["studio_50m"] is True
        assert flags["com.paid.game"]["paid_traffic_suspect"] is True
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
