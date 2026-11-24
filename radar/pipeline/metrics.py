"""Stage 5: METRICS pipeline stage.
Calculates age, install speed (V7), acceleration (ACC), chart coverage,
ratings per 1000 installs, and confidence levels.
"""
from datetime import datetime, timezone, timedelta
import logging
from typing import Dict, List, Optional, Tuple

from radar.db import Database
from radar.pipeline.track import spread_install_steps

logger = logging.getLogger("radar.pipeline.metrics")

def compute_daily_review_estimates(
    db: Database,
    app_id: str,
    real_installs: int,
    total_reviews_collected: int,
    days: int = 90
) -> Dict[str, float]:
    """Compute est_installs_day(d) = reviews_on_day(d) * (realInstalls_now / total_reviews_collected).
    Returns mapping of date string (YYYY-MM-DD) to estimated installs.
    """
    if total_reviews_collected <= 0 or real_installs <= 0:
        return {}

    multiplier = float(real_installs) / float(total_reviews_collected)

    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT date, SUM(count) as day_reviews
               FROM review_daily
               WHERE app_id = ?
               GROUP BY date
               ORDER BY date DESC
               LIMIT ?""",
            (app_id, days)
        ).fetchall()

    estimates = {}
    for r in rows:
        d_str = r["date"]
        cnt = r["day_reviews"] or 0
        estimates[d_str] = cnt * multiplier

    return estimates

def compute_coverage_for_groups(
    db: Database,
    run_id: str,
    app_id: str,
    countries_config: Dict,
    settings_config: Dict
) -> Tuple[float, float, float]:
    """Compute chart coverage over last 7 days for west, east, and all groups."""
    today_dt = datetime.now(timezone.utc)
    cutoff_date = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")

    western_codes = {c["code"].upper(): c.get("weight", 1.0) for c in countries_config.get("western", [])}
    eastern_codes = {c["code"].upper(): c.get("weight", 1.0) for c in countries_config.get("eastern", [])}

    col_weights = {
        c["id"]: c.get("weight", 1.0) for c in settings_config.get("collections", [])
    }
    col_weights["topselling_new_free"] = 1.0
    col_weights["movers_shakers"] = 1.0
    col_weights["topgrossing"] = 1.2
    col_weights["topselling_free"] = 0.8

    query = """
    SELECT country, collection, category, MIN(rank) as best_rank
    FROM chart_entries
    WHERE app_id = ?
      AND date >= ?
    GROUP BY country, collection, category
    """
    with db.get_connection() as conn:
        rows = conn.execute(query, (app_id, cutoff_date)).fetchall()

    cov_west = 0.0
    cov_east = 0.0
    cov_all = 0.0

    for r in rows:
        ctry = r["country"].upper()
        col = r["collection"]
        rank = r["best_rank"]
        clw = col_weights.get(col, 1.0)
        rank_factor = max(0.0, 1.0 - (rank - 1.0) / 200.0)

        if ctry in western_codes:
            w = western_codes[ctry]
            pts = w * clw * rank_factor
            cov_west += pts
            cov_all += pts
        elif ctry in eastern_codes:
            w = eastern_codes[ctry]
            pts = w * clw * rank_factor
            cov_east += pts
            cov_all += pts
        else:
            pts = 0.5 * clw * rank_factor
            cov_all += pts

    return cov_west, cov_east, cov_all

def calculate_game_metrics(
    db: Database,
    app_id: str,
    run_id: str,
    countries_config: Dict,
    settings_config: Dict
) -> Dict:
    today_dt = datetime.now(timezone.utc)
    today_date = today_dt.strftime("%Y-%m-%d")

    with db.get_connection() as conn:
        app_row = conn.execute("SELECT * FROM apps WHERE app_id = ?", (app_id,)).fetchone()
        snap_row = conn.execute(
            "SELECT * FROM app_snapshots WHERE app_id = ? AND run_id = ?",
            (app_id, run_id)
        ).fetchone()
        meta_row = conn.execute("SELECT * FROM backfill_meta WHERE app_id = ?", (app_id,)).fetchone()
        
        # All snapshots for this app
        all_snaps = conn.execute(
            "SELECT date, real_installs FROM app_snapshots WHERE app_id = ? ORDER BY date ASC",
            (app_id,)
        ).fetchall()

    if not app_row or not snap_row:
        return {}

    rel_date = app_row["released"] or app_row["first_seen_date"] or today_date
    try:
        rel_dt = datetime.strptime(rel_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        age_days = max(1, (today_dt - rel_dt).days)
    except Exception:
        age_days = 1

    real_installs = snap_row["real_installs"] or 0
    avg_installs_per_day = real_installs / float(max(age_days, 1))

    # Coverage
    cov_w, cov_e, cov_all = compute_coverage_for_groups(db, run_id, app_id, countries_config, settings_config)

    # Ratings per 1000 installs
    ratings = snap_row["ratings"] or 0
    ratings_per_1000 = (ratings / float(max(real_installs, 1))) * 1000.0

    # Velocity and Acceleration calculation
    v7: Optional[float] = None
    acc: Optional[float] = None
    velocity_source = "average_proxy"
    confidence = "LOW"

    snap_dates_count = len(all_snaps)
    backfill_status = meta_row["status"] if meta_row else "NONE"
    total_reviews = meta_row["total_reviews_collected"] if meta_row else 0

    if snap_dates_count >= 8:
        # Calculate from snapshots
        spread_data = spread_install_steps([dict(s) for s in all_snaps])
        # Last 7 days
        recent_7 = spread_data[-7:]
        v7 = sum(pt["spread_daily_installs"] for pt in recent_7) / 7.0
        velocity_source = "installs"
        if age_days >= 8:
            confidence = "HIGH"

        # ACC needs 15 days of snapshots
        if snap_dates_count >= 15:
            prev_7 = spread_data[-14:-7]
            v7_prev = sum(pt["spread_daily_installs"] for pt in prev_7) / 7.0
            acc = v7 / max(v7_prev, 1.0)
    else:
        # Calculate from reviews proxy
        review_estimates = compute_daily_review_estimates(db, app_id, real_installs, total_reviews, days=90)
        review_days = sorted(review_estimates.keys(), reverse=True)
        if len(review_days) >= 7:
            recent_7_days = review_days[:7]
            v7 = sum(review_estimates[d] for d in recent_7_days) / 7.0
            velocity_source = "reviews_proxy"
            if backfill_status == "COMPLETE" and total_reviews >= 200:
                confidence = "MEDIUM"

            # ACC needs 14 days of review data
            if len(review_days) >= 14:
                prev_7_days = review_days[7:14]
                v7_prev = sum(review_estimates[d] for d in prev_7_days) / 7.0
                acc = v7 / max(v7_prev, 1.0)
        else:
            v7 = avg_installs_per_day
            velocity_source = "average_proxy"
            acc = None

    return {
        "app_id": app_id,
        "age_days": age_days,
        "avg_installs_per_day": avg_installs_per_day,
        "v7": v7 if v7 is not None else avg_installs_per_day,
        "acc": acc,
        "velocity_source": velocity_source,
        "coverage_west": cov_w,
        "coverage_east": cov_e,
        "coverage_all": cov_all,
        "ratings_per_1000": ratings_per_1000,
        "confidence": confidence,
        "real_installs": real_installs,
        "score": snap_row["score"],
        "ratings": ratings
    }

def run_stage_metrics(
    db: Database,
    run_id: str,
    countries_config: Dict,
    settings_config: Dict
) -> Dict:
    """Run metrics calculation for all cohort games in this run."""
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    max_age_days = settings_config.get("max_age_days", 90)

    # Fetch cohort games for current run
    with db.get_connection() as conn:
        rows = conn.execute(
            """SELECT a.app_id FROM apps a
               JOIN app_snapshots s ON a.app_id = s.app_id AND s.run_id = ?
               WHERE a.is_old = 0""",
            (run_id,)
        ).fetchall()

    cohort_app_ids = [r["app_id"] for r in rows]
    print(f"[METRICS] Calculating metrics for {len(cohort_app_ids)} cohort games...")

    metrics_map = {}
    for aid in cohort_app_ids:
        m = calculate_game_metrics(db, aid, run_id, countries_config, settings_config)
        if m and m["age_days"] <= max_age_days:
            metrics_map[aid] = m

    summary = {
        "cohort_count": len(metrics_map),
        "high_confidence": sum(1 for m in metrics_map.values() if m["confidence"] == "HIGH"),
        "medium_confidence": sum(1 for m in metrics_map.values() if m["confidence"] == "MEDIUM"),
        "low_confidence": sum(1 for m in metrics_map.values() if m["confidence"] == "LOW")
    }
    db.set_stage_status(run_id, "METRICS", "COMPLETED", summary)
    print(f"[METRICS] Completed. Cohort games: {len(metrics_map)} (High: {summary['high_confidence']}, Medium: {summary['medium_confidence']}, Low: {summary['low_confidence']})")
    return metrics_map
