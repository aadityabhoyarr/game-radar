"""Google Play client wrapping play scrapers with rate limiting and robust parsing.
Powers:
- Chart fetching via gplay-scraper
- App detail enrichment via google-play-scraper
- Review fetching with pagination tokens via google-play-scraper
- Keyword search via google-play-scraper
- Keyword autocomplete suggestions via gplay-scraper
"""
from datetime import datetime, timezone
import dateutil.parser
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import google_play_scraper
from google_play_scraper import Sort
import gplay_scraper

from radar.limiter import get_limiter

logger = logging.getLogger("radar.play_client")

# Standard Play Store install tiers: (lower, upper)
INSTALL_TIERS = [
    (0, 1),
    (1, 5),
    (5, 10),
    (10, 50),
    (50, 100),
    (100, 500),
    (500, 1000),
    (1000, 5000),
    (5000, 10000),
    (10000, 50000),
    (50000, 100000),
    (100000, 500000),
    (500000, 1000000),
    (1000000, 5000000),
    (5000000, 10000000),
    (10000000, 50000000),
    (50000000, 100000000),
    (100000000, 500000000),
    (500000000, 1000000000),
    (1000000000, 5000000000),
]

def parse_install_bucket_midpoint(installs_label: Optional[str]) -> Tuple[Optional[int], bool]:
    """Parse install label e.g. '1,000,000+' into bucket midpoint.
    Returns (installs_count, is_estimate).
    """
    if not installs_label:
        return None, False
    clean = re.sub(r"[^\d]", "", str(installs_label))
    if not clean:
        return None, False
    val = int(clean)
    for lower, upper in INSTALL_TIERS:
        if val == lower:
            mid = (lower + upper) // 2
            return mid, True
    return val, True

def parse_date_to_iso(date_val: Any) -> Optional[str]:
    """Convert various date representations (str, datetime, timestamp, CJK dates) to YYYY-MM-DD."""
    if date_val is None:
        return None
    if isinstance(date_val, datetime):
        return date_val.strftime("%Y-%m-%d")
    if isinstance(date_val, (int, float)):
        # Check if milliseconds or seconds
        ts = date_val / 1000.0 if date_val > 1e11 else float(date_val)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    s = str(date_val).strip()
    if not s:
        return None

    # Handle CJK date patterns: YYYY年M月D日 or YYYY년 M월 D일 or YYYY. M. D. or YYYY/M/D
    cjk_m = re.search(r"(\d{4})\s*[年년\.\-/]\s*(\d{1,2})\s*[月월\.\-/]\s*(\d{1,2})", s)
    if cjk_m:
        year, month, day = cjk_m.group(1), int(cjk_m.group(2)), int(cjk_m.group(3))
        return f"{year}-{month:02d}-{day:02d}"

    # Handle European dot dates: DD.MM.YYYY
    euro_m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s)
    if euro_m:
        day, month, year = int(euro_m.group(1)), int(euro_m.group(2)), euro_m.group(3)
        return f"{year}-{month:02d}-{day:02d}"

    try:
        dt = dateutil.parser.parse(s, fuzzy=True)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

class PlayClient:
    def __init__(self):
        self.limiter = get_limiter()
        self.gplay = gplay_scraper.GPlayScraper()

    def fetch_chart(
        self,
        collection: str,
        category: str,
        country: str,
        count: int = 200,
        lang: str = "en"
    ) -> List[Dict[str, Any]]:
        """Fetch chart rankings.
        Returns list of app dicts with keys appId, title, developer, score, etc.
        """
        def _call():
            return self.gplay.list_analyze(
                collection=collection,
                category=category,
                count=count,
                lang=lang,
                country=country.lower()
            )
        return self.limiter.call(_call)

    def fetch_app_details(
        self,
        app_id: str,
        lang: str = "en",
        country: str = "us"
    ) -> Optional[Dict[str, Any]]:
        """Fetch full app metadata from google-play-scraper."""
        def _call():
            return google_play_scraper.app(
                app_id,
                lang=lang,
                country=country.lower()
            )
        try:
            return self.limiter.call(_call)
        except Exception as e:
            logger.warning(f"Failed to fetch app details for {app_id}: {e}")
            raise e

    def fetch_reviews(
        self,
        app_id: str,
        lang: str = "en",
        country: str = "us",
        count: int = 200,
        continuation_token: Optional[Any] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[Any]]:
        """Fetch reviews ordered by NEWEST."""
        def _call():
            return google_play_scraper.reviews(
                app_id,
                lang=lang,
                country=country.lower(),
                sort=Sort.NEWEST,
                count=count,
                continuation_token=continuation_token
            )
        return self.limiter.call(_call)

    def search_apps(
        self,
        query: str,
        count: int = 10,
        lang: str = "en",
        country: str = "us"
    ) -> List[Dict[str, Any]]:
        """Search apps by query."""
        def _call():
            return google_play_scraper.search(
                query,
                n_hits=count,
                lang=lang,
                country=country.lower()
            )
        return self.limiter.call(_call)

    def fetch_suggestions(
        self,
        term: str,
        country: str = "us",
        lang: str = "en"
    ) -> List[str]:
        """Fetch search autocomplete suggestions."""
        def _call():
            return self.gplay.suggest_analyze(
                term=term,
                country=country.lower(),
                lang=lang
            )
        try:
            return self.limiter.call(_call)
        except Exception as e:
            logger.warning(f"Suggestion fetch failed for '{term}': {e}")
            return []

    def fetch_developer_apps(
        self,
        dev_id: str,
        country: str = "us",
        lang: str = "en",
        count: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch developer's portfolio of games using developer_analyze or search fallback."""
        def _call():
            try:
                res = self.gplay.developer_analyze(
                    dev_id=dev_id,
                    count=count,
                    lang=lang,
                    country=country.lower()
                )
                if res:
                    return res
            except Exception:
                pass
            # Fallback search if developer_analyze did not return results
            try:
                return google_play_scraper.search(
                    dev_id,
                    n_hits=count,
                    lang=lang,
                    country=country.lower()
                )
            except Exception:
                return []
        try:
            return self.limiter.call(_call)
        except Exception as e:
            logger.warning(f"Failed to fetch developer apps for '{dev_id}': {e}")
            return []
