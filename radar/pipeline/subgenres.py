"""Stage 7: SUBGENRE TAGS pipeline stage.
Assigns subgenre tags by keyword matching on title + summary + description.
Falls back to category id if no subgenre keywords match.
"""
import json
import logging
from typing import Dict, List, Set

from radar.db import Database

logger = logging.getLogger("radar.pipeline.subgenres")

def tag_game_text(text: str, subgenre_map: Dict[str, List[str]], fallback_cat: str) -> List[str]:
    """Matches keywords in text against subgenres and returns list of assigned tags."""
    lower_text = text.lower()
    matched_tags = []

    for tag, kw_list in subgenre_map.items():
        for kw in kw_list:
            clean_kw = kw.strip().lower()
            if not clean_kw:
                continue
            # Word boundary or substring check
            if clean_kw in lower_text:
                matched_tags.append(tag)
                break

    if not matched_tags:
        matched_tags.append(fallback_cat or "GAME")

    return matched_tags

def run_stage_subgenres(
    db: Database,
    run_id: str,
    subgenres_config: Dict,
    cohort_app_ids: List[str]
) -> Dict[str, List[str]]:
    """Assigns subgenre tags to all cohort games in the run."""
    tagged_results: Dict[str, List[str]] = {}

    with db.get_connection() as conn:
        for aid in cohort_app_ids:
            row = conn.execute(
                "SELECT title, summary, description, category, genre_id FROM apps WHERE app_id = ?",
                (aid,)
            ).fetchone()
            if not row:
                continue

            title = row["title"] or ""
            summary = row["summary"] or ""
            description = row["description"] or ""
            cat = row["genre_id"] or row["category"] or "GAME"
            full_text = f"{title} {summary} {description}"

            tags = tag_game_text(full_text, subgenres_config, cat)
            tagged_results[aid] = tags

    summary = {
        "games_tagged": len(tagged_results),
        "total_tags_assigned": sum(len(t) for t in tagged_results.values()),
        "unique_tags_used": len({tag for tags in tagged_results.values() for tag in tags})
    }
    db.set_stage_status(run_id, "SUBGENRES", "COMPLETED", summary)
    print(f"[SUBGENRES] Completed. Tagged {len(tagged_results)} games with {summary['unique_tags_used']} unique tags.")
    return tagged_results
