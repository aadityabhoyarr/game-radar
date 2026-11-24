"""Stage 9: KEYWORDS pipeline stage.
Uses Google Play autocomplete suggestions and search results to evaluate
keyword demand, opportunity, brand saturation, and young cohort presence.
"""
from datetime import datetime, timezone
import json
import logging
import math
import statistics
import string
from typing import Dict, List, Optional, Set, Tuple

from radar.db import Database
from radar.play_client import PlayClient, parse_install_bucket_midpoint

logger = logging.getLogger("radar.pipeline.keywords")

def run_stage_keywords(
    db: Database,
    client: PlayClient,
    run_id: str,
    top_tags: List[str],
    subgenres_config: Dict[str, List[str]],
    brands_config: Dict,
    cohort_app_ids: Set[str],
    max_queries: int = 300
) -> List[Dict]:
    """Generates autocomplete suggestions and searches top 40 keywords for opportunity metrics."""
    print(f"[KEYWORDS] Analyzing keywords for top {len(top_tags)} tags (max {max_queries} queries)...")
    now_iso = datetime.now(timezone.utc).isoformat()
    
    big_pubs = set(p.lower() for p in brands_config.get("big_publishers", []))
    hyper_pubs = set(p.lower() for p in brands_config.get("hypercasual_publishers", []))

    # Collect seeds
    seeds = []
    for tag in top_tags[:10]:
        kw_list = subgenres_config.get(tag, [])
        for k in kw_list[:3]:
            if k and k not in seeds:
                seeds.append((k, tag))

    query_count = 0
    discovered_keywords: Dict[str, Dict] = {}

    for seed, tag in seeds:
        if query_count >= max_queries:
            break

        # Suggest for base seed
        try:
            sugs = client.fetch_suggestions(seed, country="us", lang="en")
            query_count += 1
            for rank_pos, s in enumerate(sugs or [], 1):
                clean_s = s.strip().lower()
                if clean_s not in discovered_keywords:
                    discovered_keywords[clean_s] = {
                        "keyword": clean_s,
                        "prefix_len": len(seed),
                        "rank": rank_pos,
                        "tag": tag
                    }
        except Exception as e:
            logger.warning(f"[KEYWORDS] Suggestion error for '{seed}': {e}")

        # Suggest for seed + ' ' + char
        for char in string.ascii_lowercase:
            if query_count >= max_queries:
                break
            q = f"{seed} {char}"
            try:
                sugs = client.fetch_suggestions(q, country="us", lang="en")
                query_count += 1
                for rank_pos, s in enumerate(sugs or [], 1):
                    clean_s = s.strip().lower()
                    if clean_s not in discovered_keywords:
                        discovered_keywords[clean_s] = {
                            "keyword": clean_s,
                            "prefix_len": len(q),
                            "rank": rank_pos,
                            "tag": tag
                        }
            except Exception as e:
                logger.warning(f"[KEYWORDS] Suggestion error for '{q}': {e}")

    print(f"[KEYWORDS] Harvested {len(discovered_keywords)} unique suggestion keywords from {query_count} queries.")

    # Sort keywords by demand (shorter prefix_len, better suggestion rank)
    sorted_keywords = sorted(
        discovered_keywords.values(),
        key=lambda x: (x["prefix_len"], x["rank"])
    )

    top_40 = sorted_keywords[:40]
    analyzed_keywords = []

    for idx, kw_info in enumerate(top_40, 1):
        kw = kw_info["keyword"]
        try:
            results = client.search_apps(kw, count=10, country="us", lang="en")
        except Exception as e:
            logger.warning(f"[KEYWORDS] Search error for '{kw}': {e}")
            results = []

        if not results:
            continue

        installs_list = []
        brand_count = 0
        exact_match_titles = 0
        cohort_in_top10 = 0

        for r in results:
            app_id = r.get("appId")
            title = (r.get("title") or "").lower()
            developer = (r.get("developer") or "").lower()
            
            # Installs
            inst = r.get("realInstalls")
            if not inst:
                inst, _ = parse_install_bucket_midpoint(r.get("installs"))
            installs_list.append(inst or 0)

            # Brand share
            if any(b in developer for b in big_pubs) or any(h in developer for h in hyper_pubs):
                brand_count += 1

            # Exact match
            if kw in title:
                exact_match_titles += 1

            # Cohort game in top 10
            if app_id in cohort_app_ids:
                cohort_in_top10 = 1

        med_installs = statistics.median(installs_list) if installs_list else 1000.0
        brand_share = brand_count / float(max(1, len(results)))

        # Opportunity score: high demand (shorter prefix), low median installs, low brand share, young game ranks
        # Demand index: 1.0 / log2(prefix_len + 1)
        demand_factor = 1.0 / max(1.0, math.log2(kw_info["prefix_len"] + 1))
        saturation_factor = max(0.1, 1.0 - brand_share)
        install_barrier = 1.0 / max(1.0, math.log10(max(med_installs, 100.0)))
        boost = 1.5 if cohort_in_top10 else 1.0

        opportunity = round(demand_factor * saturation_factor * install_barrier * boost * 100.0, 2)

        entry = {
            "keyword": kw,
            "locale": "en-US",
            "prefix_len": kw_info["prefix_len"],
            "median_installs": med_installs,
            "brand_share": round(brand_share, 2),
            "exact_match_titles": exact_match_titles,
            "cohort_in_top10": cohort_in_top10,
            "opportunity_score": opportunity
        }
        analyzed_keywords.append(entry)

        with db.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO keywords
                   (keyword, locale, prefix_len, search_results_json, median_installs,
                    brand_share, exact_match_titles, cohort_in_top10, opportunity_score, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    kw, "en-US", kw_info["prefix_len"], json.dumps(results[:5]),
                    med_installs, brand_share, exact_match_titles,
                    cohort_in_top10, opportunity, now_iso
                )
            )
            conn.commit()

    summary = {
        "queries_run": query_count,
        "keywords_harvested": len(discovered_keywords),
        "keywords_analyzed": len(analyzed_keywords)
    }
    db.set_stage_status(run_id, "KEYWORDS", "COMPLETED", summary)
    print(f"[KEYWORDS] Completed. Analyzed {len(analyzed_keywords)} keywords.")
    return analyzed_keywords
