"""Stage 2: ENRICH pipeline stage.
Fetches full app metadata, calculates age, tracks snapshots, and updates apps table.
Supports unlimited candidate processing (no cap), prioritization (new > tracked > stale),
freshness window skipping, crash-safe batch checkpointing, failure cooldown, and concurrency.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import json
import logging
import time
from typing import Dict, List, Optional, Set, Tuple

from radar.db import Database
from radar.play_client import PlayClient, parse_install_bucket_midpoint, parse_date_to_iso

logger = logging.getLogger("radar.pipeline.enrich")

def get_prioritized_candidates(
    db: Database,
    run_id: str,
    max_age_days: int = 90,
    enrich_fresh_days: int = 7,
    force_enrich: bool = False,
    return_fresh: bool = False
):
    """Retrieve app_ids to enrich for this run ordered by priority:
    (a) brand-new apps never enriched (priority tier 1)
    (b) tracked/high-priority apps (priority tier 2)
    (c) stale apps oldest-first (priority tier 3)

    Skips:
    - Apps already marked is_old = 1
    - Apps currently in failed_apps cooldown (e.g. 404s)
    - Apps enriched within enrich_fresh_days (unless force_enrich=True)

    Returns:
    List[str] (or Tuple[List[str], List[str]] if return_fresh=True)
    """
    query = """
    SELECT ce.app_id,
           a.is_old,
           a.released,
           MIN(CASE
               WHEN ce.collection IN ('topselling_new_free', 'movers_shakers') THEN 1
               WHEN ce.collection = 'topgrossing' THEN 2
               ELSE 3
           END) as collection_tier,
           MIN(ce.rank) as best_rank,
           MAX(s.date) as last_snapshot_date,
           COUNT(s.id) as snapshot_count
    FROM chart_entries ce
    JOIN apps a ON ce.app_id = a.app_id
    LEFT JOIN app_snapshots s ON a.app_id = s.app_id
    WHERE ce.run_id = ?
      AND a.is_old = 0
    GROUP BY ce.app_id
    """
    failed_cooldown = db.get_cooldown_failed_apps()
    today_dt = datetime.now(timezone.utc)

    brand_new = []
    tracked_priority = []
    stale_apps = []
    fresh_apps = []

    with db.get_connection() as conn:
        rows = conn.execute(query, (run_id,)).fetchall()

    for r in rows:
        aid = r["app_id"]
        if aid in failed_cooldown:
            continue

        last_snap = r["last_snapshot_date"]
        snap_count = r["snapshot_count"] or 0
        col_tier = r["collection_tier"]
        best_rank = r["best_rank"]

        # Determine freshness
        is_fresh = False
        if last_snap:
            try:
                last_dt = datetime.strptime(last_snap, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days_since = (today_dt - last_dt).days
                if days_since < enrich_fresh_days:
                    is_fresh = True
            except Exception:
                is_fresh = False

        if is_fresh and not force_enrich:
            fresh_apps.append(aid)
            continue

        # Prioritization
        if snap_count == 0 or not last_snap or r["released"] is None:
            # (a) Brand-new never enriched
            brand_new.append((col_tier, best_rank, aid))
        elif col_tier in (1, 2) or best_rank <= 50:
            # (b) Tracked / high-priority
            tracked_priority.append((col_tier, best_rank, aid))
        else:
            # (c) Stale apps, oldest last_snapshot first
            stale_apps.append((last_snap or "", col_tier, best_rank, aid))

    # Sort each group
    brand_new.sort(key=lambda x: (x[0], x[1]))
    tracked_priority.sort(key=lambda x: (x[0], x[1]))
    stale_apps.sort(key=lambda x: (x[0], x[1], x[2]))

    ordered_candidates = (
        [x[2] for x in brand_new] +
        [x[2] for x in tracked_priority] +
        [x[3] for x in stale_apps]
    )

    if return_fresh:
        return ordered_candidates, fresh_apps
    return ordered_candidates

def carry_forward_fresh_snapshots(db: Database, run_id: str, today_date: str, fresh_app_ids: List[str]):
    if not fresh_app_ids:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    with db.get_connection() as conn:
        existing = set()
        for i in range(0, len(fresh_app_ids), 500):
            chunk = fresh_app_ids[i:i + 500]
            ph = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT app_id FROM app_snapshots WHERE run_id = ? AND app_id IN ({ph})",
                [run_id] + chunk
            ).fetchall()
            existing.update(r["app_id"] for r in rows)

        needed = [aid for aid in fresh_app_ids if aid not in existing]
        if not needed:
            return

        inserts = []
        for aid in needed:
            row = conn.execute(
                "SELECT * FROM app_snapshots WHERE app_id = ? ORDER BY date DESC LIMIT 1",
                (aid,)
            ).fetchone()
            if row:
                inserts.append((
                    run_id, aid, today_date, row["real_installs"], row["installs_label"],
                    row["score"], row["ratings"], row["histogram_json"], row["updated"],
                    row["price"], row["contains_ads"], row["offers_iap"], now_iso
                ))
        if inserts:
            conn.executemany(
                """INSERT OR REPLACE INTO app_snapshots
                   (run_id, app_id, date, real_installs, installs_label, score,
                    ratings, histogram_json, updated, price, contains_ads, offers_iap, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                inserts
            )
            conn.commit()


def fetch_app_metadata(
    client: PlayClient,
    app_id: str,
    target_country: str,
    target_lang: str,
    c_code: str
) -> Tuple[str, Optional[Dict], Optional[str], Optional[str]]:
    """Fetch app details with country fallback, released date fallback, and error classification."""
    data = None
    err_type = None
    err_msg = None

    try:
        data = client.fetch_app_details(app_id, lang=target_lang, country=target_country)
    except Exception as e:
        err_str = str(e).lower()
        if "404" in err_str or "not found" in err_str:
            if target_country != "us":
                try:
                    data = client.fetch_app_details(app_id, lang="en", country="us")
                except Exception as e_us:
                    err_type = "HTTP_404_NotFound"
                    err_msg = str(e_us)
            else:
                err_type = "HTTP_404_NotFound"
                err_msg = str(e)
        else:
            if target_country != "us":
                try:
                    data = client.fetch_app_details(app_id, lang="en", country="us")
                except Exception as e_us:
                    err_type = type(e_us).__name__
                    err_msg = str(e_us)
            else:
                err_type = type(e).__name__
                err_msg = str(e)

    # Fallback for released date if missing
    if data and not data.get("released"):
        if target_country != "us":
            try:
                us_data = client.fetch_app_details(app_id, lang="en", country="us")
                if us_data and us_data.get("released"):
                    data["released"] = us_data["released"]
            except Exception:
                pass
        elif target_country == "us" and c_code != "US":
            try:
                alt_data = client.fetch_app_details(app_id, lang=target_lang, country=target_country)
                if alt_data and alt_data.get("released"):
                    data["released"] = alt_data["released"]
            except Exception:
                pass

    return app_id, data, err_type, err_msg

def run_stage_enrich(
    db: Database,
    client: PlayClient,
    run_id: str,
    settings_config: Dict,
    countries_config: Optional[Dict] = None,
    mode: str = "standard",
    enrich_cap: Optional[int] = None,
    all_candidates: bool = False,
    force_enrich: bool = False,
    enrich_workers: Optional[int] = None
) -> Dict:
    today_dt = datetime.now(timezone.utc)
    today_date = today_dt.strftime("%Y-%m-%d")
    now_iso = today_dt.isoformat()
    max_age_days = settings_config.get("max_age_days", 90)
    fresh_days = settings_config.get("enrich_fresh_days", 7)
    workers = enrich_workers if enrich_workers is not None else settings_config.get("enrich_workers", 1)

    # Locale mapping
    country_lang_map = {
        "US": "en", "GB": "en", "CA": "en", "AU": "en", "DE": "de",
        "FR": "fr", "JP": "ja", "KR": "ko", "TW": "zh_TW", "SG": "en"
    }
    if countries_config:
        for grp in ["western", "eastern"]:
            for c in countries_config.get(grp, []):
                country_lang_map[c["code"].upper()] = c.get("lang", "en")

    # Determine enrich cap: 0 or None means unlimited
    if all_candidates:
        cap = 0
    elif enrich_cap is not None:
        cap = enrich_cap
    else:
        caps = settings_config.get("enrich_cap", {"standard": 1500, "full": 0})
        cap = caps.get(mode, 1500)

    is_unlimited = (cap is None or cap == 0)

    ordered_candidates, fresh_apps = get_prioritized_candidates(
        db, run_id, max_age_days=max_age_days, enrich_fresh_days=fresh_days, force_enrich=force_enrich, return_fresh=True
    )

    # Carry forward fresh snapshots so downstream stages include them
    if fresh_apps:
        carry_forward_fresh_snapshots(db, run_id, today_date, fresh_apps)
        print(f"[ENRICH] Skipped {len(fresh_apps)} apps already enriched within {fresh_days} days (freshness window).")

    # Check already snapshotted in this run (resumability)
    already_done = set()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT app_id FROM app_snapshots WHERE run_id = ?",
            (run_id,)
        ).fetchall()
        for r in rows:
            already_done.add(r["app_id"])

    unenriched = [aid for aid in ordered_candidates if aid not in already_done]
    candidates_to_process = unenriched if is_unlimited else unenriched[:cap]
    total_to_process = len(candidates_to_process)

    cap_label = "UNLIMITED" if is_unlimited else str(cap)
    print(f"[ENRICH] Total candidates: {len(ordered_candidates)} | Fresh skipped: {len(fresh_apps)} | Already done: {len(already_done)} | To process: {total_to_process} (cap={cap_label}, workers={workers}, mode={mode})...")

    enriched_count = 0
    skipped_old = 0
    failures = 0
    cohort_count = 0
    batch_size = 25

    app_updates_batch = []
    snapshot_inserts_batch = []

    start_time = time.time()

    # Pre-fetch app info (released, is_old, first_seen) and best country for candidates
    app_meta_cache = {}
    with db.get_connection() as conn:
        app_rows = {}
        best_country = {}
        for i in range(0, len(candidates_to_process), 500):
            chunk = candidates_to_process[i:i + 500]
            ph = ",".join("?" for _ in chunk)
            for r in conn.execute(
                f"SELECT app_id, released, first_seen_date, is_old FROM apps WHERE app_id IN ({ph})",
                chunk
            ).fetchall():
                app_rows[r["app_id"]] = r
            for r in conn.execute(
                f"""SELECT app_id, country FROM (
                        SELECT app_id, country,
                            ROW_NUMBER() OVER (PARTITION BY app_id ORDER BY rank ASC) as rn
                        FROM chart_entries
                        WHERE run_id = ? AND app_id IN ({ph})
                    ) WHERE rn = 1""",
                [run_id] + chunk
            ).fetchall():
                best_country[r["app_id"]] = r["country"]

        for app_id in candidates_to_process:
            c_code = (best_country.get(app_id) or "US").upper()
            app_meta_cache[app_id] = {
                "app_row": app_rows.get(app_id),
                "c_code": c_code,
                "target_lang": country_lang_map.get(c_code, "en"),
                "target_country": c_code.lower()
            }

    def process_result(app_id: str, data: Optional[Dict], err_type: Optional[str], err_msg: Optional[str]):
        nonlocal enriched_count, skipped_old, failures, cohort_count

        if not data:
            failures += 1
            if err_type == "HTTP_404_NotFound":
                db.record_failed_app(app_id, "HTTP_404_NotFound", err_msg or "Not found on Play Store", cooldown_days=7)
            db.log_error(run_id, "ENRICH", app_id, err_type or "FetchError", err_msg or "Failed to fetch app details")
            return

        # Parse fields
        title = data.get("title")
        developer = data.get("developer")
        developer_id = data.get("developerId")
        genre = data.get("genre")
        genre_id = data.get("genreId")
        category = genre_id or genre or "GAME"
        released_raw = data.get("released")
        released_iso = parse_date_to_iso(released_raw)

        real_installs = data.get("realInstalls")
        installs_label = data.get("installs")
        if real_installs is None or real_installs == 0:
            parsed_val, _ = parse_install_bucket_midpoint(installs_label)
            real_installs = parsed_val

        score = data.get("score")
        ratings = data.get("ratings")
        histogram = json.dumps(data.get("histogram")) if data.get("histogram") else None
        updated = data.get("updated")
        price = data.get("price", 0.0)
        free = 1 if data.get("free", True) else 0
        contains_ads = 1 if (data.get("containsAds") or data.get("adSupported")) else 0
        offers_iap = 1 if data.get("offersIAP") else 0
        url = data.get("url") or f"https://play.google.com/store/apps/details?id={app_id}"
        icon = data.get("icon")
        summary = data.get("summary")
        description = data.get("description")

        # Age calculation
        meta = app_meta_cache.get(app_id, {})
        app_row = meta.get("app_row")
        is_old = 0
        age_estimated = 0
        age_days = None

        if released_iso:
            try:
                rel_dt = datetime.strptime(released_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_days = (today_dt - rel_dt).days
                if age_days > max_age_days:
                    is_old = 1
            except Exception:
                age_days = None
        else:
            age_estimated = 1
            first_seen = app_row["first_seen_date"] if (app_row and app_row["first_seen_date"]) else today_date
            try:
                fs_dt = datetime.strptime(first_seen, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_days = (today_dt - fs_dt).days
                if age_days > max_age_days:
                    is_old = 1
            except Exception:
                age_days = None

        if is_old:
            skipped_old += 1
        else:
            cohort_count += 1

        app_updates_batch.append((
            title, developer, developer_id, category,
            genre, genre_id, released_iso, age_estimated,
            is_old, price, free, contains_ads,
            offers_iap, url, icon, summary,
            description, now_iso, app_id
        ))

        snapshot_inserts_batch.append((
            run_id, app_id, today_date, real_installs, installs_label, score,
            ratings, histogram, updated, price, contains_ads, offers_iap, now_iso
        ))

        enriched_count += 1

    # Execution: sequential or threaded
    if workers <= 1:
        for idx, app_id in enumerate(candidates_to_process, 1):
            meta = app_meta_cache[app_id]
            app_row = meta["app_row"]
            if app_row and app_row["is_old"]:
                skipped_old += 1
                continue

            _, data, err_type, err_msg = fetch_app_metadata(
                client, app_id, meta["target_country"], meta["target_lang"], meta["c_code"]
            )
            process_result(app_id, data, err_type, err_msg)

            # Checkpoint commit
            if len(app_updates_batch) >= batch_size:
                db.save_enrich_batch(run_id, app_updates_batch, snapshot_inserts_batch)
                app_updates_batch.clear()
                snapshot_inserts_batch.clear()
                db.set_stage_status(run_id, "ENRICH", "IN_PROGRESS", {
                    "processed": enriched_count,
                    "total": total_to_process,
                    "failures": failures,
                    "skipped_old": skipped_old,
                    "skipped_fresh": len(fresh_apps)
                })

            # Stats logging every 50 apps
            if idx % 50 == 0 or idx == total_to_process:
                elapsed = time.time() - start_time
                rate = enriched_count / max(elapsed, 0.1)
                remaining = total_to_process - idx
                eta_sec = remaining / max(rate, 0.01)
                eta_str = f"{int(eta_sec // 60)}m {int(eta_sec % 60)}s"
                pct = (idx / total_to_process) * 100 if total_to_process > 0 else 100.0
                limiter = client.limiter
                print(
                    f"[ENRICH] {idx}/{total_to_process} ({pct:.1f}%) | "
                    f"Enriched: {enriched_count} | Failures: {failures} | "
                    f"Old: {skipped_old} | Fresh: {len(fresh_apps)} | "
                    f"Speed: {rate:.1f} apps/s | Req: {limiter.request_count} | "
                    f"Err breakdown: {dict(limiter.errors_by_reason)} | ETA: {eta_str}"
                )
    else:
        # Multi-worker concurrent execution with shared rate limiter
        idx = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_app = {
                executor.submit(
                    fetch_app_metadata,
                    client,
                    aid,
                    app_meta_cache[aid]["target_country"],
                    app_meta_cache[aid]["target_lang"],
                    app_meta_cache[aid]["c_code"]
                ): aid
                for aid in candidates_to_process
                if not (app_meta_cache[aid]["app_row"] and app_meta_cache[aid]["app_row"]["is_old"])
            }
            for future in as_completed(future_to_app):
                idx += 1
                try:
                    app_id, data, err_type, err_msg = future.result()
                except Exception as exc:
                    app_id = future_to_app[future]
                    data, err_type, err_msg = None, type(exc).__name__, str(exc)
                process_result(app_id, data, err_type, err_msg)

                if len(app_updates_batch) >= batch_size:
                    db.save_enrich_batch(run_id, app_updates_batch, snapshot_inserts_batch)
                    app_updates_batch.clear()
                    snapshot_inserts_batch.clear()
                    db.set_stage_status(run_id, "ENRICH", "IN_PROGRESS", {
                        "processed": enriched_count,
                        "total": total_to_process,
                        "failures": failures,
                        "skipped_old": skipped_old,
                        "skipped_fresh": len(fresh_apps)
                    })

                if idx % 50 == 0 or idx == len(future_to_app):
                    elapsed = time.time() - start_time
                    rate = enriched_count / max(elapsed, 0.1)
                    remaining = len(future_to_app) - idx
                    eta_sec = remaining / max(rate, 0.01)
                    eta_str = f"{int(eta_sec // 60)}m {int(eta_sec % 60)}s"
                    pct = (idx / len(future_to_app)) * 100 if len(future_to_app) > 0 else 100.0
                    limiter = client.limiter
                    print(
                        f"[ENRICH] {idx}/{len(future_to_app)} ({pct:.1f}%) | "
                        f"Enriched: {enriched_count} | Failures: {failures} | "
                        f"Old: {skipped_old} | Fresh: {len(fresh_apps)} | "
                        f"Speed: {rate:.1f} apps/s | Req: {limiter.request_count} | "
                        f"Err breakdown: {dict(limiter.errors_by_reason)} | ETA: {eta_str}"
                    )

    # Final batch commit
    if app_updates_batch or snapshot_inserts_batch:
        db.save_enrich_batch(run_id, app_updates_batch, snapshot_inserts_batch)
        app_updates_batch.clear()
        snapshot_inserts_batch.clear()

    summary = {
        "total_candidates": len(ordered_candidates),
        "processed": enriched_count,
        "cohort_young_apps": cohort_count,
        "skipped_old": skipped_old,
        "skipped_fresh": len(fresh_apps),
        "failures": failures
    }
    db.set_stage_status(run_id, "ENRICH", "COMPLETED", summary)
    print(f"[ENRICH] Completed. Enriched: {enriched_count}, Young cohort: {cohort_count}, Old skipped: {skipped_old}, Fresh skipped: {len(fresh_apps)}, Failures: {failures}")
    return summary
