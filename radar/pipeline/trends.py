"""Stage 10: TRENDS pipeline stage.
Pulls 12-month Google Trends data via pytrends with 10s sleep between calls.
Calculates 12-week slope and latest value. Stops gracefully on 429.
"""
from datetime import datetime, timezone
import logging
import time
from typing import Dict, List, Optional

from radar.db import Database

logger = logging.getLogger("radar.pipeline.trends")

def calculate_12w_slope(values: List[float]) -> float:
    """Calculates linear slope over the last 12 weekly data points."""
    if len(values) < 2:
        return 0.0
    recent = values[-12:]
    n = len(recent)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(recent) / float(n)
    numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    return round(numerator / denominator, 3) if denominator != 0 else 0.0

def run_stage_trends(
    db: Database,
    run_id: str,
    keywords_list: List[str],
    region: str = "US",
    max_keywords: int = 15
) -> Dict[str, Dict]:
    """Fetches trends for keywords, sleeping 10s between calls and stopping on 429."""
    print(f"[TRENDS] Fetching Google Trends for up to {max_keywords} keywords (10s delay between calls)...")
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
    except Exception as e:
        logger.warning(f"[TRENDS] pytrends not available: {e}")
        db.set_stage_status(run_id, "TRENDS", "SKIPPED", {"reason": str(e)})
        return {}

    trends_results = {}
    hit_rate_limit = False

    for idx, kw in enumerate(keywords_list[:max_keywords], 1):
        clean_kw = kw.strip()
        if not clean_kw:
            continue

        try:
            pt.build_payload([clean_kw], timeframe="today 12-m", geo=region)
            df = pt.interest_over_time()
            if not df.empty and clean_kw in df.columns:
                series = [float(v) for v in df[clean_kw].tolist()]
                latest_val = series[-1] if series else 0.0
                slope = calculate_12w_slope(series)

                trends_results[clean_kw] = {
                    "keyword": clean_kw,
                    "region": region,
                    "latest_value": latest_val,
                    "slope_12w": slope
                }

                with db.get_connection() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO trends_cache
                           (keyword, region, latest_value, slope_12w, updated_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (clean_kw, region, latest_val, slope, now_iso)
                    )
                    conn.commit()
            print(f"[TRENDS] {idx}/{min(len(keywords_list), max_keywords)}: '{clean_kw}' -> Latest: {latest_val}, 12w Slope: {slope}")
        except Exception as e:
            err_msg = str(e).lower()
            if "429" in err_msg or "too many requests" in err_msg:
                print(f"[TRENDS] Rate limit 429 encountered on '{clean_kw}'. Halting trends gracefully.")
                hit_rate_limit = True
                db.log_error(run_id, "TRENDS", clean_kw, "RateLimit429", str(e))
                break
            else:
                logger.warning(f"[TRENDS] Error for '{clean_kw}': {e}")
                db.log_error(run_id, "TRENDS", clean_kw, type(e).__name__, str(e))

        # Polite 10s sleep between Google Trends calls
        if idx < min(len(keywords_list), max_keywords):
            time.sleep(10.0)

    summary = {
        "keywords_checked": len(trends_results),
        "hit_rate_limit": hit_rate_limit
    }
    db.set_stage_status(run_id, "TRENDS", "COMPLETED", summary)
    print(f"[TRENDS] Completed. Retrieved trends for {len(trends_results)} keywords.")
    return trends_results
