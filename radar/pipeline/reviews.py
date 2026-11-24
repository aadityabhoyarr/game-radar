"""Stage 3: REVIEWS BACKFILL pipeline stage.
Pulls dated reviews newest-first, aggregates by day without storing review text,
and enables day-one growth velocity via review proxies.
"""
from datetime import datetime, timezone, timedelta
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from radar.db import Database
from radar.play_client import PlayClient, parse_date_to_iso

logger = logging.getLogger("radar.pipeline.reviews")

def serialize_token(tok) -> Optional[str]:
    if tok is None:
        return None
    if isinstance(tok, str):
        if tok.startswith("<"):
            return None
        return tok
    if hasattr(tok, "token"):
        return json.dumps({
            "token": tok.token,
            "lang": getattr(tok, "lang", "en"),
            "country": getattr(tok, "country", "us"),
            "sort": getattr(tok, "sort", 2),
            "count": getattr(tok, "count", 200),
            "filter_score_with": getattr(tok, "filter_score_with", None),
            "filter_device_with": getattr(tok, "filter_device_with", None),
        })
    return str(tok)

def deserialize_token(tok_str: Optional[str]) -> Optional[Any]:
    if not tok_str:
        return None
    if tok_str.startswith("{"):
        try:
            d = json.loads(tok_str)
            from google_play_scraper.features.reviews import _ContinuationToken
            return _ContinuationToken(
                token=d.get("token"),
                lang=d.get("lang", "en"),
                country=d.get("country", "us"),
                sort=d.get("sort", 2),
                count=d.get("count", 200),
                filter_score_with=d.get("filter_score_with"),
                filter_device_with=d.get("filter_device_with")
            )
        except Exception:
            return None
    return None

def compute_cohort_prescores(db: Database, run_id: str, max_age_days: int = 90) -> List[Dict]:
    """Calculate pre-score = chart_coverage * freshness * percentile(avg_installs_per_day)."""
    today_dt = datetime.now(timezone.utc)
    today_date = today_dt.strftime("%Y-%m-%d")

    # Fetch cohort games with latest snapshots and coverage
    query = """
    SELECT a.app_id, a.released, a.first_seen_date, a.age_estimated,
           s.real_installs, s.score, s.ratings
    FROM apps a
    JOIN app_snapshots s ON a.app_id = s.app_id AND s.run_id = ?
    WHERE a.is_old = 0
    """
    with db.get_connection() as conn:
        apps = conn.execute(query, (run_id,)).fetchall()
        
        # Coverage calculation per app
        cov_query = """
        SELECT app_id, country, collection, MIN(rank) as best_rank
        FROM chart_entries
        WHERE run_id = ?
        GROUP BY app_id, country, collection
        """
        cov_rows = conn.execute(cov_query, (run_id,)).fetchall()

    cov_by_app: Dict[str, float] = {}
    locales_by_app: Dict[str, List[Tuple[str, int]]] = {}

    # Weight lookup
    country_weights = {
        "US": 1.0, "JP": 1.0, "KR": 0.9, "GB": 0.8, "DE": 0.8,
        "CA": 0.7, "AU": 0.7, "FR": 0.7, "TW": 0.6, "SG": 0.4
    }
    col_weights = {
        "topselling_new_free": 1.0,
        "movers_shakers": 1.0,
        "topgrossing": 1.2,
        "topselling_free": 0.8
    }

    for r in cov_rows:
        aid = r["app_id"]
        ctry = r["country"].upper()
        col = r["collection"]
        rank = r["best_rank"]
        cw = country_weights.get(ctry, 0.5)
        clw = col_weights.get(col, 1.0)
        rank_factor = max(0.0, 1.0 - (rank - 1.0) / 200.0)
        pts = cw * clw * rank_factor
        cov_by_app[aid] = cov_by_app.get(aid, 0.0) + pts

        if aid not in locales_by_app:
            locales_by_app[aid] = []
        locales_by_app[aid].append((ctry, rank))

    candidates = []
    for r in apps:
        aid = r["app_id"]
        rel = r["released"] or r["first_seen_date"] or today_date
        try:
            rel_dt = datetime.strptime(rel, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            age_days = max(1, (today_dt - rel_dt).days)
        except Exception:
            age_days = 1

        if age_days > max_age_days:
            continue

        installs = r["real_installs"] or 1
        avg_installs = installs / float(age_days)
        freshness = max(0.01, 1.0 - (age_days / float(max_age_days)))
        cov = cov_by_app.get(aid, 0.1)

        # Top 1-2 chart locales
        sorted_locs = sorted(locales_by_app.get(aid, [("US", 100)]), key=lambda x: x[1])
        top_locs = [x[0] for x in sorted_locs[:2]]

        candidates.append({
            "app_id": aid,
            "age_days": age_days,
            "avg_installs": avg_installs,
            "freshness": freshness,
            "coverage": cov,
            "top_locales": top_locs,
            "release_date": rel,
            "real_installs": installs
        })

    if not candidates:
        return []

    # Compute percentile of avg_installs
    sorted_by_installs = sorted(candidates, key=lambda x: x["avg_installs"])
    n = len(sorted_by_installs)
    for rank_idx, item in enumerate(sorted_by_installs):
        item["installs_percentile"] = (rank_idx + 1) / float(n)
        item["pre_score"] = item["coverage"] * item["freshness"] * item["installs_percentile"]

    candidates.sort(key=lambda x: x["pre_score"], reverse=True)
    return candidates

def run_stage_reviews(
    db: Database,
    client: PlayClient,
    run_id: str,
    countries_config: Dict,
    settings_config: Dict,
    mode: str = "standard"
) -> Dict:
    review_caps = settings_config.get("review_caps", {"standard": 8000, "full": 20000})
    review_cap = review_caps.get(mode, 8000)

    games_caps = settings_config.get("review_games_cap", {"standard": 60, "full": 300})
    games_cap = games_caps.get(mode, 60)

    candidates = compute_cohort_prescores(db, run_id, settings_config.get("max_age_days", 90))
    top_games = candidates[:games_cap]

    print(f"[REVIEWS] Selected top {len(top_games)} games for backfill (cap={review_cap} reviews/game)...")

    # Locale lang mapping
    country_langs = {}
    for grp in ["western", "eastern"]:
        for c in countries_config.get(grp, []):
            country_langs[c["code"].upper()] = (c.get("lang", "en"), c["code"].lower())

    complete_count = 0
    partial_count = 0
    total_reviews_fetched = 0

    for idx, game in enumerate(top_games, 1):
        app_id = game["app_id"]
        rel_date_str = game["release_date"]
        try:
            rel_dt = datetime.strptime(rel_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            cutoff_dt = rel_dt - timedelta(days=1)
        except Exception:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=95)

        # Check existing backfill metadata
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with db.get_connection() as conn:
            meta = conn.execute("SELECT * FROM backfill_meta WHERE app_id = ?", (app_id,)).fetchone()
        
        meta_token_str = meta["token"] if meta else None
        token = deserialize_token(meta_token_str)
        prev_status = meta["status"] if meta else "PENDING"
        collected_for_game = meta["total_reviews_collected"] if meta else 0

        # If already completed today, count and skip refetching
        if prev_status == "COMPLETE" and meta and meta["last_review_date"] == today_date:
            complete_count += 1
            total_reviews_fetched += collected_for_game
            if idx % 10 == 0 or idx == len(top_games):
                print(f"[REVIEWS] {idx}/{len(top_games)} apps | Already completed: {app_id} ({collected_for_game} reviews)")
            continue

        # Locales to pull
        locales = game["top_locales"] or ["US"]
        stop_backfill = False
        status = "COMPLETE"

        for ctry in locales:
            if stop_backfill:
                break
            lang, gl = country_langs.get(ctry, ("en", "us"))
            locale_key = f"{lang}-{gl.upper()}"

            while collected_for_game < review_cap:
                try:
                    rvs, next_token = client.fetch_reviews(
                        app_id=app_id,
                        lang=lang,
                        country=gl,
                        count=200,
                        continuation_token=token
                    )
                except Exception as e:
                    logger.warning(f"[REVIEWS] Error fetching reviews for {app_id}: {e}")
                    db.log_error(run_id, "REVIEWS", app_id, type(e).__name__, str(e))
                    break

                if not rvs:
                    status = "COMPLETE"
                    break

                # Aggregate by day
                daily_counts: Dict[str, Dict[str, float]] = {}
                reached_cutoff = False

                for rv in rvs:
                    at_val = rv.get("at")
                    if isinstance(at_val, datetime):
                        rv_dt = at_val.replace(tzinfo=timezone.utc) if at_val.tzinfo is None else at_val
                    else:
                        iso_str = parse_date_to_iso(at_val)
                        rv_dt = datetime.strptime(iso_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if iso_str else datetime.now(timezone.utc)

                    if rv_dt < cutoff_dt:
                        reached_cutoff = True
                        break

                    day_str = rv_dt.strftime("%Y-%m-%d")
                    score_val = float(rv.get("score", 0))

                    if day_str not in daily_counts:
                        daily_counts[day_str] = {"count": 0, "sum_score": 0.0}
                    daily_counts[day_str]["count"] += 1
                    daily_counts[day_str]["sum_score"] += score_val

                    collected_for_game += 1
                    total_reviews_fetched += 1

                # Save daily aggregates to DB
                with db.get_connection() as conn:
                    for day_str, agg in daily_counts.items():
                        conn.execute(
                            """INSERT INTO review_daily (app_id, locale, date, count, sum_score, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?)
                               ON CONFLICT(app_id, locale, date) DO UPDATE SET
                               count = count + excluded.count,
                               sum_score = sum_score + excluded.sum_score,
                               updated_at = excluded.updated_at""",
                            (app_id, locale_key, day_str, agg["count"], agg["sum_score"], datetime.now(timezone.utc).isoformat())
                        )
                    conn.commit()

                if reached_cutoff:
                    status = "COMPLETE"
                    stop_backfill = True
                    break

                if collected_for_game >= review_cap:
                    status = "PARTIAL"
                    stop_backfill = True
                    break

                if not next_token:
                    status = "COMPLETE"
                    break

                token = next_token

        # Save meta
        if status == "COMPLETE":
            complete_count += 1
        else:
            partial_count += 1

        with db.get_connection() as conn:
            conn.execute(
                """INSERT INTO backfill_meta (app_id, status, token, last_review_date, total_reviews_collected, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(app_id) DO UPDATE SET
                   status = excluded.status,
                   token = excluded.token,
                   last_review_date = excluded.last_review_date,
                   total_reviews_collected = excluded.total_reviews_collected,
                   updated_at = excluded.updated_at""",
                (
                    app_id, status, serialize_token(token),
                    datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    collected_for_game,
                    datetime.now(timezone.utc).isoformat()
                )
            )
            conn.commit()

        if idx % 10 == 0 or idx == len(top_games):
            print(f"[REVIEWS] {idx}/{len(top_games)} apps | Current: {app_id} | Total Reviews: {collected_for_game} ({status})")

    summary = {
        "games_considered": len(candidates),
        "games_backfilled": len(top_games),
        "complete_backfills": complete_count,
        "partial_backfills": partial_count,
        "total_reviews": total_reviews_fetched
    }
    db.set_stage_status(run_id, "REVIEWS", "COMPLETED", summary)
    print(f"[REVIEWS] Completed. Backfilled: {len(top_games)}, COMPLETE: {complete_count}, PARTIAL: {partial_count}")
    return summary
