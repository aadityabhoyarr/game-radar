from radar.pipeline.score import compute_percentiles

def test_compute_percentiles():
    values = [10.0, 50.0, 20.0, None, 100.0]
    pcts = compute_percentiles(values)
    # Valid sorted: 10 (idx 0), 20 (idx 2), 50 (idx 1), 100 (idx 4)
    # Total valid = 4
    assert pcts[0] == 0.25
    assert pcts[2] == 0.50
    assert pcts[1] == 0.75
    assert pcts[4] == 1.00
    assert pcts[3] == 0.0

def test_trend_score_components():
    from radar.db import Database
    from radar.pipeline.score import run_stage_score

    # Setup dummy database in memory
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_path = tf.name

    try:
        db = Database(temp_path)
        cohort_metrics = {
            "com.test.game1": {
                "age_days": 10,
                "score": 4.5,
                "ratings": 100,
                "v7": 5000.0,
                "acc": 1.5,
                "coverage_west": 5.0,
                "coverage_east": 4.0,
                "coverage_all": 9.0,
                "confidence": "HIGH"
            },
            "com.test.game2": {
                "age_days": 80,
                "score": 3.2,
                "ratings": 20, # < 50 ratings -> rating comp = 0
                "v7": 1000.0,
                "acc": None, # Missing ACC
                "coverage_west": 1.0,
                "coverage_east": 1.0,
                "coverage_all": 2.0,
                "confidence": "LOW"
            }
        }
        scores = run_stage_score(db, "run_test", cohort_metrics)
        assert len(scores) == 2
        g1 = scores["com.test.game1"]
        g2 = scores["com.test.game2"]

        assert g1["trend_score_all"] > g2["trend_score_all"]
        assert g2["acc_missing"] is True
        assert g2["comp_acc"] == 0.0
        assert g2["comp_rating"] == 0.0
        assert g1["comp_freshness"] > g2["comp_freshness"]
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
