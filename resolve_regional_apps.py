import json
import logging
from datetime import datetime, timezone
import sqlite3
import google_play_scraper
from radar.play_client import parse_date_to_iso, parse_install_bucket_midpoint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resolve")

def resolve():
    conn = sqlite3.connect("data/radar.db")
    conn.row_factory = sqlite3.Row
    today_dt = datetime.now(timezone.utc)
    today_date = today_dt.strftime("%Y-%m-%d")

    # Map country to lang
    with open("config/countries.json", "r", encoding="utf-8") as f:
        countries_cfg = json.load(f)

    country_lang_map = {}
    for grp in ["western", "eastern"]:
        for c in countries_cfg.get(grp, []):
            country_lang_map[c["code"].upper()] = (c.get("lang", "en"), c["code"].lower())

    # Find cohort apps with released IS NULL
    rows = conn.execute("""
        SELECT a.app_id, ce.country, MIN(ce.rank) as best_rank
        FROM apps a
        JOIN chart_entries ce ON a.app_id = ce.app_id
        WHERE a.is_old = 0 AND a.released IS NULL
        GROUP BY a.app_id
    """).fetchall()

    logger.info(f"Resolving {len(rows)} apps with NULL release dates...")

    old_marked = 0
    young_resolved = 0
    still_null = 0

    for idx, r in enumerate(rows, 1):
        app_id = r["app_id"]
        c_code = (r["country"] or "US").upper()
        lang, gl = country_lang_map.get(c_code, ("en", "us"))

        data = None
        # Try native country
        try:
            data = google_play_scraper.app(app_id, lang=lang, country=gl)
        except Exception:
            pass

        # Try US fallback if native failed or returned no release date
        if not data or not data.get("released"):
            try:
                us_data = google_play_scraper.app(app_id, lang="en", country="us")
                if us_data and us_data.get("released"):
                    data = us_data
                elif not data and us_data:
                    data = us_data
            except Exception:
                pass

        if not data:
            still_null += 1
            logger.info(f"[{idx}/{len(rows)}] {app_id}: Not found in {gl} or US")
            continue

        raw_rel = data.get("released")
        iso_rel = parse_date_to_iso(raw_rel)
        is_old = 0
        age_days = None

        if iso_rel:
            try:
                rel_dt = datetime.strptime(iso_rel, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age_days = (today_dt - rel_dt).days
                if age_days > 90:
                    is_old = 1
            except Exception:
                pass
        else:
            age_days = 1

        if is_old:
            old_marked += 1
            logger.info(f"[{idx}/{len(rows)}] {app_id}: OLD! Released {iso_rel} ({age_days}d ago)")
            conn.execute("UPDATE apps SET released = ?, is_old = 1, age_estimated = 0 WHERE app_id = ?", (iso_rel, app_id))
            conn.execute("DELETE FROM cohort_metrics WHERE app_id = ?", (app_id,))
        else:
            young_resolved += 1
            logger.info(f"[{idx}/{len(rows)}] {app_id}: YOUNG! Released {iso_rel} ({age_days}d ago)")
            conn.execute("UPDATE apps SET released = ?, is_old = 0, age_estimated = ? WHERE app_id = ?", (iso_rel, 0 if iso_rel else 1, app_id))

        conn.commit()

    logger.info(f"Done! Old marked: {old_marked}, Young resolved: {young_resolved}, Still null: {still_null}")

if __name__ == "__main__":
    resolve()
