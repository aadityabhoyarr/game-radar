"""Stage 1: CHARTS pipeline stage.
Pulls top charts across countries, categories, and collections.
Stores chart entries and records newly seen apps.
"""
from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Optional

from radar.db import Database
from radar.play_client import PlayClient

logger = logging.getLogger("radar.pipeline.charts")

def run_stage_charts(
    db: Database,
    client: PlayClient,
    run_id: str,
    countries_config: Dict,
    settings_config: Dict,
    mode: str = "standard"
) -> Dict:
    """Run chart scanning across configured countries, categories, collections."""
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).isoformat()
    
    western = countries_config.get("western", [])
    eastern = countries_config.get("eastern", [])
    all_countries = western + eastern

    categories = settings_config.get("categories", ["GAME"])
    collections = settings_config.get("collections", [
        {"id": "topselling_new_free", "name": "TOP_NEW_FREE", "weight": 1.0},
        {"id": "movers_shakers", "name": "TRENDING", "weight": 1.0},
        {"id": "topgrossing", "name": "TOP_GROSSING", "weight": 1.2},
        {"id": "topselling_free", "name": "TOP_FREE", "weight": 0.8}
    ])

    chart_depth = settings_config.get("chart_depth", 200)

    # In standard mode, if running a standard scan, we cover all collections.
    # Total combinations
    tasks = []
    for c in all_countries:
        for cat in categories:
            for col in collections:
                tasks.append((c, cat, col))

    total_tasks = len(tasks)
    print(f"[CHARTS] Starting chart scan: {total_tasks} chart targets (depth={chart_depth})...")

    # Check already completed tasks for this run_id for resumability
    completed_keys = set()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT country, category, collection FROM chart_entries WHERE run_id = ?",
            (run_id,)
        ).fetchall()
        for r in rows:
            completed_keys.add((r["country"], r["category"], r["collection"]))

    apps_seen = set()
    new_apps_count = 0
    total_entries_stored = 0
    failures = 0

    for idx, (country_obj, cat, col_obj) in enumerate(tasks, 1):
        ctry_code = country_obj["code"]
        lang = country_obj.get("lang", "en")
        col_id = col_obj["id"]

        if (ctry_code, cat, col_id) in completed_keys:
            continue

        try:
            apps_list = client.fetch_chart(
                collection=col_id,
                category=cat,
                country=ctry_code,
                count=chart_depth,
                lang=lang
            )
        except Exception as e:
            failures += 1
            err_type = type(e).__name__
            err_msg = str(e)
            logger.warning(f"[CHARTS] Failed {ctry_code}/{cat}/{col_id}: {err_msg}")
            db.log_error(run_id, "CHARTS", f"{ctry_code}/{cat}/{col_id}", err_type, err_msg)
            continue

        if not apps_list:
            continue

        with db.get_connection() as conn:
            for rank, app_data in enumerate(apps_list, 1):
                app_id = app_data.get("appId")
                if not app_id:
                    continue

                apps_seen.add(app_id)

                # Store chart entry
                conn.execute(
                    """INSERT OR IGNORE INTO chart_entries
                       (run_id, date, country, category, collection, rank, app_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, today_date, ctry_code, cat, col_id, rank, app_id)
                )

                # Insert unknown app if not yet seen
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO apps (app_id, first_seen_date, updated_at)
                       VALUES (?, ?, ?)""",
                    (app_id, today_date, now_iso)
                )
                if cursor.rowcount > 0:
                    new_apps_count += 1
                total_entries_stored += 1

            conn.commit()

        if idx % 20 == 0 or idx == total_tasks:
            pct = (idx / total_tasks) * 100
            print(f"[CHARTS] Progress: {idx}/{total_tasks} ({pct:.1f}%) | Unique apps seen: {len(apps_seen)}")

    summary = {
        "total_targets": total_tasks,
        "completed_targets": total_tasks - failures,
        "failed_targets": failures,
        "total_entries": total_entries_stored,
        "unique_apps_seen": len(apps_seen),
        "new_apps_inserted": new_apps_count
    }
    db.set_stage_status(run_id, "CHARTS", "COMPLETED", summary)
    print(f"[CHARTS] Completed. Apps seen: {len(apps_seen)}, new apps: {new_apps_count}, failures: {failures}")
    return summary
