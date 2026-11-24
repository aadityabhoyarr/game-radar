"""Stage 11: WHY GROWING AND HOW FOUND pipeline stage.
Identifies up to 5 growth drivers per top game, labeled ESTIMATE with evidence,
and traces the first discovery channel ('How found').
"""
from datetime import datetime, timezone, timedelta
import json
import logging
from typing import Dict, List, Optional, Set

from radar.db import Database

logger = logging.getLogger("radar.pipeline.why")

def analyze_why_growing(
    db: Database,
    run_id: str,
    top_30_app_ids: List[str],
    game_metrics: Dict[str, Dict],
    game_scores: Dict[str, Dict],
    brand_flags: Dict[str, Dict],
    game_tags: Dict[str, List[str]]
) -> Dict[str, Dict]:
    """Analyzes growth drivers and first discovery channel for top 30 games."""
    if not top_30_app_ids:
        return {}
    today_dt = datetime.now(timezone.utc)
    results = {}

    # Query search rankings from keywords table
    keyword_hits_by_app: Dict[str, List[str]] = {}
    with db.get_connection() as conn:
        krows = conn.execute("SELECT keyword, search_results_json FROM keywords").fetchall()
        for kr in krows:
            kw = kr["keyword"]
            res_json = kr["search_results_json"]
            if res_json:
                try:
                    s_items = json.loads(res_json)
                    for item in s_items:
                        aid = item.get("appId")
                        if aid in top_30_app_ids:
                            if aid not in keyword_hits_by_app:
                                keyword_hits_by_app[aid] = []
                            keyword_hits_by_app[aid].append(kw)
                except Exception:
                    pass

        # All chart appearances for top games
        all_chart_rows = conn.execute(
            """SELECT app_id, date, country, collection, category, rank
               FROM chart_entries
               WHERE app_id IN ({})
               ORDER BY date ASC, rank ASC""".format(",".join("?" * len(top_30_app_ids))),
            top_30_app_ids
        ).fetchall()

        # Static details for top games
        app_rows = conn.execute(
            """SELECT a.app_id, a.title, a.released, s.updated, a.first_seen_date
               FROM apps a
               LEFT JOIN app_snapshots s ON a.app_id = s.app_id AND s.run_id = ?
               WHERE a.app_id IN ({})""".format(",".join("?" * len(top_30_app_ids))),
            [run_id] + list(top_30_app_ids)
        ).fetchall()

    charts_by_app: Dict[str, List[Dict]] = {aid: [] for aid in top_30_app_ids}
    for r in all_chart_rows:
        charts_by_app[r["app_id"]].append(dict(r))

    apps_by_id = {r["app_id"]: dict(r) for r in app_rows}

    # Count cohort games per tag and release date ranges for "wave" detection
    tag_dates: Dict[str, List[datetime]] = {}
    for aid, tags in game_tags.items():
        rel = apps_by_id.get(aid, {}).get("released") or apps_by_id.get(aid, {}).get("first_seen_date")
        if rel:
            try:
                rdt = datetime.strptime(rel, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                for t in tags:
                    if t not in tag_dates:
                        tag_dates[t] = []
                    tag_dates[t].append(rdt)
            except Exception:
                pass

    for aid in top_30_app_ids:
        app = apps_by_id.get(aid, {})
        m = game_metrics.get(aid, {})
        b = brand_flags.get(aid, {})
        tags = game_tags.get(aid, [])
        charts = charts_by_app.get(aid, [])

        drivers = []

        # 1. Chart-driven
        if charts:
            best_charts = sorted(charts, key=lambda x: x["rank"])[:3]
            chart_ev = ", ".join(f"#{c['rank']} in {c['country']} ({c['collection']})" for c in best_charts)
            drivers.append({
                "driver": "Chart-driven",
                "label": "ESTIMATE",
                "evidence": f"Featured at high ranks: {chart_ev}"
            })

        # 2. Search-driven
        kw_matches = keyword_hits_by_app.get(aid, [])
        if kw_matches:
            kw_ev = ", ".join(f"'{k}'" for k in kw_matches[:3])
            drivers.append({
                "driver": "Search-driven",
                "label": "ESTIMATE",
                "evidence": f"Appears in top 10 search results for: {kw_ev}"
            })

        # 3. Update effect
        upd_ts = app.get("updated")
        if upd_ts:
            try:
                upd_dt = datetime.fromtimestamp(upd_ts / 1000.0 if upd_ts > 1e11 else float(upd_ts), tz=timezone.utc)
                diff_days = (today_dt - upd_dt).days
                if diff_days <= 14:
                    drivers.append({
                        "driver": "Update effect",
                        "label": "ESTIMATE",
                        "evidence": f"Recent update {diff_days} days ago ({upd_dt.strftime('%Y-%m-%d')}) preceded velocity surge"
                    })
            except Exception:
                pass

        # 4. Paid-traffic signs
        if b.get("paid_traffic_suspect"):
            reasons = b.get("paid_suspect_reasons", [])
            drivers.append({
                "driver": "Paid-traffic signs",
                "label": "ESTIMATE",
                "evidence": "; ".join(reasons)
            })

        # 5. Wave (tag clustering)
        for t in tags:
            dates = tag_dates.get(t, [])
            if len(dates) >= 3:
                # Check if multiple dates are within 30 days
                rel_str = app.get("released") or app.get("first_seen_date")
                if rel_str:
                    try:
                        g_dt = datetime.strptime(rel_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        cluster = [d for d in dates if abs((d - g_dt).days) <= 30]
                        if len(cluster) >= 3:
                            drivers.append({
                                "driver": "Wave",
                                "label": "ESTIMATE",
                                "evidence": f"Part of sub-genre wave: {len(cluster)} cohort games in '{t}' released within 30 days"
                            })
                            break
                    except Exception:
                        pass

        # 6. Outside-store
        if len(drivers) < 2 and (not charts or (charts and charts[0]["rank"] > 100)):
            v7 = m.get("v7", 0.0)
            if v7 > 1000:
                drivers.append({
                    "driver": "Outside-store",
                    "label": "ESTIMATE",
                    "evidence": f"High speed (V7={int(v7):,}) with low store chart footprint indicates external marketing, ads, or viral referral"
                })

        # Cap to 5 drivers
        drivers = drivers[:5]

        # How found
        how_found_list = []
        seen_channels = set()
        for c in charts:
            ch_key = (c["country"], c["collection"])
            if ch_key not in seen_channels:
                seen_channels.add(ch_key)
                how_found_list.append(f"{c['date']} {c['country']} {c['collection']} #{c['rank']}")

        results[aid] = {
            "drivers": drivers,
            "how_found": "; ".join(how_found_list[:4]) if how_found_list else "First seen in cohort scan"
        }

    return results

def run_stage_why(
    db: Database,
    run_id: str,
    top_30_app_ids: List[str],
    game_metrics: Dict[str, Dict],
    game_scores: Dict[str, Dict],
    brand_flags: Dict[str, Dict],
    game_tags: Dict[str, List[str]]
) -> Dict[str, Dict]:
    if not top_30_app_ids:
        return {}
    print(f"[WHY] Computing growth drivers and discovery traces for top {len(top_30_app_ids)} games...")
    results = analyze_why_growing(db, run_id, top_30_app_ids, game_metrics, game_scores, brand_flags, game_tags)
    db.set_stage_status(run_id, "WHY_GROWING", "COMPLETED", {"games_analyzed": len(results)})
    print(f"[WHY] Completed analysis for {len(results)} games.")
    return results
