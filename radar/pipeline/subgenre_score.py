"""Sub-genre Build Now Score calculation for West, East, and All groups.
Evaluates:
- Momentum (35)
- Breadth (15)
- Openness (20)
- Demand (20) / DEMAND_MISSING redistribution
- Monetization (10)
Plus evidence games.
"""
from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Optional, Set, Tuple

from radar.db import Database
from radar.pipeline.score import compute_percentiles

logger = logging.getLogger("radar.pipeline.subgenre_score")

def compute_build_now_scores(
    db: Database,
    run_id: str,
    subgenres_config: Dict[str, List[str]],
    game_tags: Dict[str, List[str]],
    game_scores: Dict[str, Dict],
    brand_flags: Dict[str, Dict],
    game_metrics: Dict[str, Dict],
    keyword_metrics: Optional[List[Dict]] = None,
    trends_metrics: Optional[Dict[str, Dict]] = None
) -> Dict[str, List[Dict]]:
    """Calculates Build Now Score (0-100) per tag for 'west', 'east', and 'all'."""
    now_iso = datetime.now(timezone.utc).isoformat()
    groups = ["west", "east", "all"]

    # Gather games per tag
    tag_to_apps: Dict[str, List[str]] = {t: [] for t in subgenres_config.keys()}
    for aid, tags in game_tags.items():
        for t in tags:
            if t not in tag_to_apps:
                tag_to_apps[t] = []
            tag_to_apps[t].append(aid)

    # Fetch app titles and IAP flags
    app_info: Dict[str, Dict] = {}
    with db.get_connection() as conn:
        for aid in game_scores.keys():
            row = conn.execute("SELECT title, offers_iap FROM apps WHERE app_id = ?", (aid,)).fetchone()
            if row:
                app_info[aid] = dict(row)

        # Check which apps appeared in topgrossing
        grossing_apps = set()
        grows = conn.execute(
            "SELECT DISTINCT app_id FROM chart_entries WHERE run_id = ? AND collection = 'topgrossing'",
            (run_id,)
        ).fetchall()
        for gr in grows:
            grossing_apps.add(gr["app_id"])

    # Map tag to keyword demand if available
    tag_demand_map: Dict[str, float] = {}
    if keyword_metrics:
        # Check opportunity score for seeds
        for km in keyword_metrics:
            # Match kw to tag
            kw = km["keyword"]
            for t, kw_list in subgenres_config.items():
                if any(k in kw for k in kw_list):
                    tag_demand_map[t] = max(tag_demand_map.get(t, 0.0), km.get("opportunity_score", 0.0))

    results_by_group: Dict[str, List[Dict]] = {}

    for grp in groups:
        score_key = f"trend_score_{grp}"
        tag_data_list = []

        # Step 1: Compute raw metrics for tags with cohort games
        for tag, aids in tag_to_apps.items():
            if not aids:
                continue

            total_cohort = len(aids)
            # Scores for games in this tag
            scored_games = []
            for aid in aids:
                sc = game_scores.get(aid, {}).get(score_key, 0.0)
                scored_games.append((aid, sc))
            scored_games.sort(key=lambda x: x[1], reverse=True)

            # 1. Momentum: mean Trend Score of top 5
            top_5 = scored_games[:5]
            mean_momentum = sum(x[1] for x in top_5) / float(len(top_5))
            raw_momentum = (mean_momentum / 100.0) * 35.0

            # 2. Breadth raw: count of games with Trend Score >= 50
            breadth_count = sum(1 for x in scored_games if x[1] >= 50.0)

            # 3. Openness: share not hit by default-hidden brand flags
            open_count = sum(1 for aid in aids if not brand_flags.get(aid, {}).get("hidden_by_default", False))
            openness_share = open_count / float(total_cohort)
            raw_openness = openness_share * 20.0

            # 4. Monetization: share appearing in topgrossing or offering IAP
            monetized_count = sum(
                1 for aid in aids
                if (aid in grossing_apps or app_info.get(aid, {}).get("offers_iap", 0) == 1)
            )
            monetization_share = monetized_count / float(total_cohort)
            raw_monetization = monetization_share * 10.0

            # 5. Demand
            demand_val = tag_demand_map.get(tag)

            # Evidence games
            evidence = []
            for aid, sc in top_5:
                evidence.append({
                    "app_id": aid,
                    "title": app_info.get(aid, {}).get("title") or aid,
                    "trend_score": sc
                })

            tag_data_list.append({
                "tag": tag,
                "total_games": total_cohort,
                "raw_momentum": raw_momentum,
                "breadth_count": breadth_count,
                "raw_openness": raw_openness,
                "raw_monetization": raw_monetization,
                "demand_val": demand_val,
                "evidence": evidence
            })

        if not tag_data_list:
            results_by_group[grp] = []
            continue

        # Compute percentiles for breadth and demand
        breadth_counts = [td["breadth_count"] for td in tag_data_list]
        demand_vals = [td["demand_val"] for td in tag_data_list]
        breadth_pcts = compute_percentiles(breadth_counts)
        has_any_demand = any(v is not None for v in demand_vals)
        demand_pcts = compute_percentiles(demand_vals) if has_any_demand else {}

        ranked_tags = []
        for idx, td in enumerate(tag_data_list):
            tag = td["tag"]
            c_mom = td["raw_momentum"]
            c_brd = breadth_pcts[idx] * 15.0
            c_opn = td["raw_openness"]
            c_mon = td["raw_monetization"]

            demand_missing = not has_any_demand or (td["demand_val"] is None)
            if demand_missing:
                # Redistribute 20 points proportionally over other components (multiplier = 100/80 = 1.25)
                c_mom *= 1.25
                c_brd *= 1.25
                c_opn *= 1.25
                c_mon *= 1.25
                c_dmd = 0.0
            else:
                c_dmd = demand_pcts.get(idx, 0.0) * 20.0

            total_bns = round(c_mom + c_brd + c_opn + c_dmd + c_mon, 2)

            entry = {
                "tag": tag,
                "build_now_score": total_bns,
                "comp_momentum": round(c_mom, 2),
                "comp_breadth": round(c_brd, 2),
                "comp_openness": round(c_opn, 2),
                "comp_demand": round(c_dmd, 2),
                "comp_monetization": round(c_mon, 2),
                "demand_missing": demand_missing,
                "total_cohort_games": td["total_games"],
                "evidence_games": td["evidence"]
            }
            ranked_tags.append(entry)

            # Store in DB
            with db.get_connection() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO subgenre_scores
                       (run_id, tag, group_name, build_now_score, comp_momentum, comp_breadth,
                        comp_openness, comp_demand, comp_monetization, evidence_games_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id, tag, grp, total_bns, round(c_mom, 2), round(c_brd, 2),
                        round(c_opn, 2), round(c_dmd, 2), round(c_mon, 2),
                        json.dumps(td["evidence"])
                    )
                )
                conn.commit()

        ranked_tags.sort(key=lambda x: x["build_now_score"], reverse=True)
        results_by_group[grp] = ranked_tags

    summary = {
        grp: len(results_by_group[grp]) for grp in groups
    }
    db.set_stage_status(run_id, "SUBGENRE_SCORES", "COMPLETED", summary)
    print(f"[SUBGENRES] Build Now Scores computed for {len(results_by_group.get('all', []))} tags.")
    return results_by_group
