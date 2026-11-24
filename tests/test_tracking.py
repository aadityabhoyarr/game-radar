from radar.pipeline.track import spread_install_steps

def test_spread_install_steps():
    # 4 days of snapshots with a jump from 10k to 16k across days 1 -> 4 (3 days interval)
    snaps = [
        {"date": "2026-11-01", "real_installs": 10000},
        {"date": "2026-11-02", "real_installs": 10000},
        {"date": "2026-11-03", "real_installs": 10000},
        {"date": "2026-11-04", "real_installs": 16000},
    ]
    res = spread_install_steps(snaps)
    assert len(res) == 4

    # Day 1: baseline
    assert res[0]["raw_installs"] == 10000
    assert res[0]["has_counter_update"] is True

    # Day 2: flat day (no raw update), spread speed is 6000 / 3 = 2000
    assert res[1]["raw_installs"] == 10000
    assert res[1]["has_counter_update"] is False
    assert res[1]["spread_daily_installs"] == 2000.0

    # Day 3: flat day
    assert res[2]["raw_installs"] == 10000
    assert res[2]["has_counter_update"] is False
    assert res[2]["spread_daily_installs"] == 2000.0

    # Day 4: jump day, update is True, spread speed is 2000
    assert res[3]["raw_installs"] == 16000
    assert res[3]["has_counter_update"] is True
    assert res[3]["spread_daily_installs"] == 2000.0
