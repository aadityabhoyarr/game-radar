"""Stage 8: TREND SCORE pipeline stage.
Calculates 0-100 Trend Score and individual components for west, east, and all groups.
Computes percentiles within the current cohort.
"""
import logging
from typing import Dict, List, Optional, Tuple

from radar.db import Database

logger = logging.getLogger("radar.pipeline.score")

def compute_percentiles(values: List[Optional[float]]) -> Dict[int, float]:
    """Compute empirical percentile (0.0 to 1.0) for each element by index.
    None values receive 0.0.
    """
    n = len(values)
    if n == 0:
        return {}

    # Separate valid numbers and their indices
    valid = [(idx, val) for idx, val in enumerate(values) if val is not None]
    if not valid:
        return {idx: 0.0 for idx in range(n)}

    valid_sorted = sorted(valid, key=lambda x: x[1])
    m = len(valid_sorted)

    pct_by_idx = {idx: 0.0 for idx in range(n)}
    for rank_idx, (orig_idx, _) in enumerate(valid_sorted, 1):
        pct_by_idx[orig_idx] = rank_idx / float(m)

    return pct_by_idx

def run_stage_score(
    db: Database,
    run_id: str,
    cohort_metrics: Dict[str, Dict]
) -> Dict[str, Dict]:
    """Calculates Trend Score (0-100) and its 5 components for all cohort games."""
    app_ids = list(cohort_metrics.keys())
    if not app_ids:
        return {}

    n = len(app_ids)

    # Extract value lists for percentiles
    v7_list = [cohort_metrics[aid].get("v7", 0.0) for aid in app_ids]
    acc_list = [cohort_metrics[aid].get("acc") for aid in app_ids]
    cov_w_list = [cohort_metrics[aid].get("coverage_west", 0.0) for aid in app_ids]
    cov_e_list = [cohort_metrics[aid].get("coverage_east", 0.0) for aid in app_ids]
    cov_all_list = [cohort_metrics[aid].get("coverage_all", 0.0) for aid in app_ids]

    v7_pcts = compute_percentiles(v7_list)
    acc_pcts = compute_percentiles(acc_list)
    cov_w_pcts = compute_percentiles(cov_w_list)
    cov_e_pcts = compute_percentiles(cov_e_list)
    cov_all_pcts = compute_percentiles(cov_all_list)

    scores_result = {}

    for idx, aid in enumerate(app_ids):
        m = cohort_metrics[aid]
        age_days = m.get("age_days", 90)
        score_val = m.get("score")
        ratings_cnt = m.get("ratings") or 0

        # 1. V7 speed: percentile * 40
        c_v7 = v7_pcts[idx] * 40.0

        # 2. ACC acceleration: percentile * 15 (0 if None)
        has_acc = (m.get("acc") is not None)
        c_acc = (acc_pcts[idx] * 15.0) if has_acc else 0.0

        # 3. Freshness: 15 * (1 - age / 90)
        c_freshness = 15.0 * max(0.0, min(1.0, 1.0 - (age_days / 90.0)))

        # 4. Coverage: percentile * 20
        c_cov_w = cov_w_pcts[idx] * 20.0
        c_cov_e = cov_e_pcts[idx] * 20.0
        c_cov_all = cov_all_pcts[idx] * 20.0

        # 5. Rating: 10 * clip((score - 3.0)/2.0, 0, 1) only if ratings >= 50
        if ratings_cnt >= 50 and score_val is not None:
            clipped_rating = max(0.0, min(1.0, (float(score_val) - 3.0) / 2.0))
            c_rating = 10.0 * clipped_rating
        else:
            c_rating = 0.0

        score_w = round(c_v7 + c_acc + c_freshness + c_cov_w + c_rating, 2)
        score_e = round(c_v7 + c_acc + c_freshness + c_cov_e + c_rating, 2)
        score_all = round(c_v7 + c_acc + c_freshness + c_cov_all + c_rating, 2)

        scores_result[aid] = {
            "trend_score_west": score_w,
            "trend_score_east": score_e,
            "trend_score_all": score_all,
            "comp_v7": round(c_v7, 2),
            "comp_acc": round(c_acc, 2),
            "comp_freshness": round(c_freshness, 2),
            "comp_coverage_west": round(c_cov_w, 2),
            "comp_coverage_east": round(c_cov_e, 2),
            "comp_coverage_all": round(c_cov_all, 2),
            "comp_rating": round(c_rating, 2),
            "acc_missing": not has_acc,
            "confidence": m.get("confidence", "LOW")
        }

    summary = {
        "games_scored": len(scores_result),
        "mean_score_all": round(sum(s["trend_score_all"] for s in scores_result.values()) / max(1, len(scores_result)), 2)
    }
    db.set_stage_status(run_id, "SCORE", "COMPLETED", summary)
    print(f"[SCORE] Completed. Scored {len(scores_result)} games. Mean score: {summary['mean_score_all']}")
    return scores_result
