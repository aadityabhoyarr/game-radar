"""Stage 6: BRANDS pipeline stage.
Flags big publishers, hypercasual publishers, franchises, large studios,
and identifies paid traffic suspect indicators.
"""
from datetime import datetime, timezone, timedelta
import json
import logging
import statistics
from typing import Dict, List, Optional, Set, Tuple

from radar.db import Database
from radar.play_client import parse_install_bucket_midpoint

logger = logging.getLogger("radar.pipeline.brands")

def match_brand_names(text: Optional[str], names: List[str], exact_match: bool = False) -> bool:
    if not text:
        return False
    lower_text = text.strip().lower()
    for name in names:
        n = name.strip().lower()
        if not n:
            continue
        if exact_match:
            if lower_text == n:
                return True
        else:
            if n in lower_text:
                return True
    return False

def run_stage_brands(
    db: Database,
    run_id: str,
    brands_config: Dict,
    cohort_metrics: Dict[str, Dict],
    client: Optional[Any] = None
) -> Dict[str, Dict]:
    """Tag cohort games with brand flags and paid traffic suspect heuristics."""
    big_pubs = brands_config.get("big_publishers", [])
    hyper_pubs = brands_config.get("hypercasual_publishers", [])
    franchises = brands_config.get("franchises", [])
    now_iso = datetime.now(timezone.utc).isoformat()

    # Fetch app metadata for cohort games
    cohort_aids = list(cohort_metrics.keys())
    if not cohort_aids:
        return {}

    app_details: Dict[str, Dict] = {}
    with db.get_connection() as conn:
        for aid in cohort_aids:
            row = conn.execute("SELECT * FROM apps WHERE app_id = ?", (aid,)).fetchone()
            if row:
                app_details[aid] = dict(row)

        # Developer aggregates across database
        dev_stats: Dict[str, Tuple[int, int]] = {}
        rows = conn.execute("""
            SELECT developer, COUNT(DISTINCT a.app_id) as g_cnt,
                   SUM(COALESCE(s.real_installs, 0)) as total_installs
            FROM apps a
            LEFT JOIN app_snapshots s ON a.app_id = s.app_id AND s.run_id = ?
            WHERE developer IS NOT NULL AND developer != ''
            GROUP BY developer
        """, (run_id,)).fetchall()
        for r in rows:
            dev_stats[r["developer"]] = (r["total_installs"] or 0, r["g_cnt"] or 0)

        # Country appearance counts in current run
        ctry_counts: Dict[str, int] = {}
        crows = conn.execute("""
            SELECT app_id, COUNT(DISTINCT country) as c_cnt
            FROM chart_entries
            WHERE run_id = ?
            GROUP BY app_id
        """, (run_id,)).fetchall()
        for cr in crows:
            ctry_counts[cr["app_id"]] = cr["c_cnt"]

        # Fetch cached developer pages (30 days validity)
        cached_devs: Dict[str, Tuple[int, int]] = {}
        d_rows = conn.execute("""
            SELECT developer_id, total_installs, game_count
            FROM developer_cache
            WHERE fetched_at >= datetime('now', '-30 days')
        """).fetchall()
        for dr in d_rows:
            cached_devs[dr["developer_id"]] = (dr["total_installs"] or 0, dr["game_count"] or 0)

    # Sort cohort games by velocity/coverage to identify top 300 candidates for developer check
    top_300_aids = sorted(
        cohort_aids,
        key=lambda aid: cohort_metrics[aid].get("v7", 0.0) + cohort_metrics[aid].get("coverage_all", 0.0) * 100.0,
        reverse=True
    )[:300]

    if client:
        # Check developers of top 300 apps not yet cached
        checked_dev_keys = set()
        for aid in top_300_aids:
            app = app_details.get(aid, {})
            dev_id = app.get("developer_id") or app.get("developer")
            if not dev_id or dev_id in cached_devs or dev_id in checked_dev_keys:
                continue
            checked_dev_keys.add(dev_id)
            try:
                dev_apps = client.fetch_developer_apps(dev_id)
                if dev_apps:
                    total_inst = 0
                    for da in dev_apps:
                        ri = da.get("realInstalls")
                        if not ri:
                            parsed_mid, _ = parse_install_bucket_midpoint(da.get("installs"))
                            ri = parsed_mid or 0
                        total_inst += ri
                    g_count = len(dev_apps)
                    with db.get_connection() as conn:
                        conn.execute("""
                            INSERT OR REPLACE INTO developer_cache
                            (developer_id, dev_name, total_installs, game_count, games_json, fetched_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (dev_id, app.get("developer"), total_inst, g_count, json.dumps(dev_apps[:20]), now_iso))
                        conn.commit()
                    cached_devs[dev_id] = (total_inst, g_count)
            except Exception as e:
                logger.warning(f"Failed to check developer {dev_id}: {e}")

    # Calculate median ratings_per_1000 by category
    ratings_by_cat: Dict[str, List[float]] = {}
    for aid, m in cohort_metrics.items():
        cat = app_details.get(aid, {}).get("category", "GAME")
        if cat not in ratings_by_cat:
            ratings_by_cat[cat] = []
        ratings_by_cat[cat].append(m.get("ratings_per_1000", 0.0))

    cat_medians: Dict[str, float] = {}
    for cat, vals in ratings_by_cat.items():
        cat_medians[cat] = statistics.median(vals) if vals else 0.0

    flagged_results = {}

    for aid, m in cohort_metrics.items():
        app = app_details.get(aid, {})
        title = app.get("title") or ""
        developer = app.get("developer") or ""
        category = app.get("category") or "GAME"
        age_days = m.get("age_days", 90)
        ratings_p1k = m.get("ratings_per_1000", 0.0)

        is_big = match_brand_names(developer, big_pubs)
        is_hyper = match_brand_names(developer, hyper_pubs)
        is_franchise = match_brand_names(title, franchises)

        # Developer studio size (checks database aggregate and cached developer page)
        dev_installs, dev_games = dev_stats.get(developer, (0, 0))
        dev_key = app.get("developer_id") or developer
        c_installs, c_games = cached_devs.get(dev_key, (0, 0))
        studio_50m = (dev_installs >= 50_000_000) or (c_installs >= 50_000_000)
        studio_40plus = (dev_games >= 40) or (c_games >= 40)

        # Paid traffic heuristic
        cat_med = cat_medians.get(category, 0.0)
        paid_reasons = []

        if cat_med > 0 and ratings_p1k < (0.5 * cat_med):
            paid_reasons.append(f"Low rating ratio ({ratings_p1k:.1f}/1k vs cat median {cat_med:.1f}/1k)")
        if is_hyper:
            paid_reasons.append("Known hyper-casual publisher")
        
        country_cnt = ctry_counts.get(aid, 1)
        if country_cnt <= 2 and age_days < 21:
            paid_reasons.append(f"Soft launch footprint ({country_cnt} countries, age {age_days}d)")

        paid_suspect = len(paid_reasons) > 0
        hidden_by_default = is_big or is_hyper or is_franchise

        flags_dict = {
            "big_publisher": is_big,
            "hypercasual_publisher": is_hyper,
            "franchise": is_franchise,
            "studio_50m": studio_50m,
            "studio_40plus": studio_40plus,
            "paid_traffic_suspect": paid_suspect,
            "hidden_by_default": hidden_by_default,
            "paid_suspect_reasons": paid_reasons
        }
        flagged_results[aid] = flags_dict

    summary = {
        "total_analyzed": len(flagged_results),
        "big_publishers": sum(1 for f in flagged_results.values() if f["big_publisher"]),
        "hypercasual": sum(1 for f in flagged_results.values() if f["hypercasual_publisher"]),
        "franchises": sum(1 for f in flagged_results.values() if f["franchise"]),
        "paid_suspects": sum(1 for f in flagged_results.values() if f["paid_traffic_suspect"]),
        "hidden_by_default": sum(1 for f in flagged_results.values() if f["hidden_by_default"])
    }
    db.set_stage_status(run_id, "BRANDS", "COMPLETED", summary)
    print(f"[BRANDS] Completed. Big: {summary['big_publishers']}, Hypercasual: {summary['hypercasual']}, Franchises: {summary['franchises']}, Paid suspects: {summary['paid_suspects']}, Hidden: {summary['hidden_by_default']}")
    return flagged_results
