"""Preflight check module for Game Radar.
Tests live APIs and saves capabilities to data/capabilities.json.
"""
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys

logger = logging.getLogger("radar.preflight")

def run_preflight(output_path: str = "data/capabilities.json") -> dict:
    """Run live preflight capability checks against Google Play and trends."""
    print("Running preflight capability checks...")
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "google_play_scraper": {
            "installed": False,
            "version": None,
            "app_fields_confirmed": False,
            "missing_fields": [],
            "reviews_works": False,
            "search_works": False,
        },
        "gplay_scraper": {
            "installed": False,
            "version": None,
            "collections": {},
            "categories_supported": [],
            "max_count": 0,
            "suggest_works": False,
        },
        "pytrends": {
            "installed": False,
            "works": False,
        },
        "node_bridge": {
            "needed": False,
            "node_installed": False,
        }
    }

    # 1. Test google-play-scraper
    try:
        import google_play_scraper
        import importlib.metadata
        try:
            ver = importlib.metadata.version("google-play-scraper")
        except Exception:
            ver = getattr(google_play_scraper, "__version__", "unknown")
        results["google_play_scraper"]["installed"] = True
        results["google_play_scraper"]["version"] = ver

        # Check app()
        from google_play_scraper import app, reviews, search, Sort
        target_fields = [
            "released", "installs", "realInstalls", "score", "ratings",
            "histogram", "offersIAP", "adSupported", "containsAds",
            "genre", "genreId", "developer", "developerId", "updated",
            "free", "price", "summary", "description", "title"
        ]
        sample_app = app("com.nianticlabs.pokemongo")
        missing = [f for f in target_fields if f not in sample_app]
        results["google_play_scraper"]["missing_fields"] = missing
        results["google_play_scraper"]["app_fields_confirmed"] = (len(missing) == 0)

        # Check reviews()
        rvs, token = reviews("com.nianticlabs.pokemongo", count=5, sort=Sort.NEWEST)
        has_at = len(rvs) > 0 and "at" in rvs[0]
        results["google_play_scraper"]["reviews_works"] = bool(has_at and (token is not None))

        # Check search()
        s_res = search("puzzle", n_hits=3)
        results["google_play_scraper"]["search_works"] = (len(s_res) > 0)
    except Exception as e:
        logger.warning(f"google-play-scraper preflight error: {e}")

    # 2. Test gplay-scraper
    try:
        import gplay_scraper
        import importlib.metadata
        try:
            gp_ver = importlib.metadata.version("gplay-scraper")
        except Exception:
            gp_ver = getattr(gplay_scraper, "__version__", "unknown")
        results["gplay_scraper"]["installed"] = True
        results["gplay_scraper"]["version"] = gp_ver

        scraper = gplay_scraper.GPlayScraper()
        
        # Test collections
        test_cols = ["topselling_new_free", "movers_shakers", "topgrossing", "topselling_free", "TOP_NEW_FREE"]
        max_c = 0
        for col in test_cols:
            try:
                res = scraper.list_analyze(collection=col, category="GAME", count=20, country="us")
                count = len(res)
                results["gplay_scraper"]["collections"][col] = (count > 0)
                if count > 0:
                    max_c = max(max_c, 200)
            except Exception:
                results["gplay_scraper"]["collections"][col] = False
        results["gplay_scraper"]["max_count"] = max_c

        # Test categories
        cats = [
            "GAME", "GAME_ACTION", "GAME_ADVENTURE", "GAME_ARCADE", "GAME_BOARD",
            "GAME_CARD", "GAME_CASINO", "GAME_CASUAL", "GAME_EDUCATIONAL", "GAME_MUSIC",
            "GAME_PUZZLE", "GAME_RACING", "GAME_ROLE_PLAYING", "GAME_SIMULATION",
            "GAME_SPORTS", "GAME_STRATEGY", "GAME_TRIVIA", "GAME_WORD"
        ]
        supported_cats = []
        for cat in cats:
            try:
                res = scraper.list_analyze(collection="topselling_free", category=cat, count=2, country="us")
                if len(res) > 0:
                    supported_cats.append(cat)
            except Exception:
                pass
        results["gplay_scraper"]["categories_supported"] = supported_cats

        # Test suggest
        try:
            sugs = scraper.suggest_analyze(term="puzzle", country="us")
            results["gplay_scraper"]["suggest_works"] = (len(sugs) > 0)
        except Exception:
            results["gplay_scraper"]["suggest_works"] = False
    except Exception as e:
        logger.warning(f"gplay-scraper preflight error: {e}")

    # 3. Test pytrends
    try:
        import pytrends
        from pytrends.request import TrendReq
        import importlib.metadata
        try:
            pt_ver = importlib.metadata.version("pytrends")
        except Exception:
            pt_ver = getattr(pytrends, "__version__", "unknown")
        results["pytrends"]["installed"] = True
        results["pytrends"]["version"] = pt_ver

        pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
        pt.build_payload(["puzzle"], timeframe="today 12-m", geo="US")
        df = pt.interest_over_time()
        results["pytrends"]["works"] = not df.empty
    except Exception as e:
        logger.warning(f"pytrends preflight error: {e}")

    # 4. Node check
    import shutil
    node_bin = shutil.which("node")
    results["node_bridge"]["node_installed"] = bool(node_bin)
    results["node_bridge"]["needed"] = not (
        results["gplay_scraper"]["collections"].get("topselling_free") and
        results["gplay_scraper"]["suggest_works"]
    )

    # Save
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return results

if __name__ == "__main__":
    capabilities = run_preflight("data/capabilities.json")
    print(json.dumps(capabilities, indent=2))
