"""Stage 4: TRACK pipeline stage.
Appends today's snapshots and calculates smoothed install velocity across step-wise counter jumps.
Spreads counter changes evenly over elapsed days and marks non-update days.
"""
from datetime import datetime, timezone, timedelta
import logging
from typing import Dict, List, Optional, Tuple

from radar.db import Database

logger = logging.getLogger("radar.pipeline.track")

def spread_install_steps(snapshots: List[Dict]) -> List[Dict]:
    """Calculate spread install velocity between discrete Google install counter updates.
    snapshots: list of dicts with 'date' (YYYY-MM-DD) and 'real_installs' (int), sorted ascending by date.
    Returns list of dicts with:
      - date: YYYY-MM-DD
      - raw_installs: int or None
      - has_counter_update: bool
      - spread_daily_installs: float
    """
    if not snapshots:
        return []

    # Filter out missing installs
    valid_points = [s for s in snapshots if s.get("real_installs") is not None]
    if not valid_points:
        return []

    results = []
    # Identify change points
    change_indices = [0]
    for i in range(1, len(valid_points)):
        if valid_points[i]["real_installs"] != valid_points[i - 1]["real_installs"]:
            change_indices.append(i)

    # If the last index is not a change index, include it to spread the latest span
    if change_indices[-1] != len(valid_points) - 1:
        change_indices.append(len(valid_points) - 1)

    spread_map: Dict[str, Tuple[bool, float]] = {}

    for idx_pos in range(len(change_indices) - 1):
        start_idx = change_indices[idx_pos]
        end_idx = change_indices[idx_pos + 1]

        start_pt = valid_points[start_idx]
        end_pt = valid_points[end_idx]

        d1 = datetime.strptime(start_pt["date"], "%Y-%m-%d")
        d2 = datetime.strptime(end_pt["date"], "%Y-%m-%d")
        days_span = max(1, (d2 - d1).days)

        delta_installs = max(0, (end_pt["real_installs"] or 0) - (start_pt["real_installs"] or 0))
        daily_speed = delta_installs / float(days_span)

        # For days in between, spread the speed
        curr_d = d1 + timedelta(days=1)
        while curr_d <= d2:
            d_str = curr_d.strftime("%Y-%m-%d")
            # Day has raw update only if it is the end change point and raw values differed
            is_update = (curr_d == d2) and (end_pt["real_installs"] != start_pt["real_installs"])
            spread_map[d_str] = (is_update, daily_speed)
            curr_d += timedelta(days=1)

    # Initial day
    first_pt = valid_points[0]
    spread_map[first_pt["date"]] = (True, 0.0)

    for pt in valid_points:
        d_str = pt["date"]
        is_update, speed = spread_map.get(d_str, (False, 0.0))
        results.append({
            "date": d_str,
            "raw_installs": pt["real_installs"],
            "has_counter_update": is_update,
            "spread_daily_installs": speed
        })

    return results

def run_stage_track(db: Database, run_id: str) -> Dict:
    """Verifies all cohort apps have today's snapshot recorded and calculates tracking summary."""
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    with db.get_connection() as conn:
        # Check snapshot count for this run
        row = conn.execute(
            "SELECT COUNT(DISTINCT app_id) as cnt FROM app_snapshots WHERE run_id = ?",
            (run_id,)
        ).fetchone()
        snapshots_count = row["cnt"] if row else 0

        # Total days of history recorded
        days_row = conn.execute(
            "SELECT COUNT(DISTINCT date) as days_cnt FROM app_snapshots"
        ).fetchone()
        total_days = days_row["days_cnt"] if days_row else 1

    summary = {
        "snapshots_recorded": snapshots_count,
        "total_days_tracked": total_days,
        "date": today_date
    }
    db.set_stage_status(run_id, "TRACK", "COMPLETED", summary)
    print(f"[TRACK] Completed. Snapshots in this run: {snapshots_count}, Total historical days: {total_days}")
    return summary
