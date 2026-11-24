"""Global polite rate limiter and request wrapper for Game Radar.
Enforces:
- Max 1.5 requests per second
- Random jitter 0.2 - 0.6 s
- Exponential backoff with up to 5 retries
- 60 s cooldown after 429 or 403
- Optional proxy rotation
"""
from datetime import datetime, timezone
import logging
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("radar.limiter")

class RateLimiter:
    def __init__(
        self,
        max_rps: float = 1.5,
        jitter_min: float = 0.2,
        jitter_max: float = 0.6,
        max_retries: int = 5,
        cooldown_seconds: float = 60.0,
        proxies: Optional[List[str]] = None,
    ):
        self.min_interval = 1.0 / max(max_rps, 0.1)
        self.jitter_min = jitter_min
        self.jitter_max = jitter_max
        self.max_retries = max_retries
        self.cooldown_seconds = cooldown_seconds
        self.proxies = list(proxies) if proxies else []
        self._proxy_idx = 0
        self._last_call_time = 0.0
        self._lock = threading.Lock()
        self._cooldown_until = 0.0
        # Stats tracking
        self.request_count = 0
        self.failure_count = 0
        self.errors_by_reason: Dict[str, int] = {}

    def get_current_proxy(self) -> Optional[str]:
        with self._lock:
            if not self.proxies:
                return None
            return self.proxies[self._proxy_idx % len(self.proxies)]

    def rotate_proxy(self):
        with self._lock:
            if self.proxies:
                self._proxy_idx = (self._proxy_idx + 1) % len(self.proxies)

    def _wait_for_turn(self):
        with self._lock:
            now = time.time()
            jitter = random.uniform(self.jitter_min, self.jitter_max)
            next_slot = max(self._last_call_time + self.min_interval + jitter, self._cooldown_until)
            wait_time = max(0.0, next_slot - now)
            self._last_call_time = now + wait_time
        if wait_time > 0:
            time.sleep(wait_time)

    def record_error(self, reason: str):
        with self._lock:
            self.failure_count += 1
            self.errors_by_reason[reason] = self.errors_by_reason.get(reason, 0) + 1

    def call(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        """Call fn(*args, **kwargs) obeying rate limits and retry rules."""
        retries = 0
        while True:
            self._wait_for_turn()
            with self._lock:
                self.request_count += 1
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                err_str = str(e).lower()
                status_code = getattr(e, "status_code", None)
                if status_code is None and hasattr(e, "response") and hasattr(e.response, "status_code"):
                    status_code = e.response.status_code
                
                is_rate_limit = (status_code == 429) or ("429" in err_str) or ("too many requests" in err_str)
                is_forbidden = (status_code == 403) or ("403" in err_str) or ("forbidden" in err_str)
                is_server_error = (status_code and 500 <= status_code < 600) or any(code in err_str for code in ["500", "502", "503", "504"]) or ("server error" in err_str) or ("bad gateway" in err_str) or ("service unavailable" in err_str)
                is_timeout = ("timeout" in err_str) or ("timed out" in err_str)
                is_not_found = (status_code == 404) or ("404" in err_str) or ("not found" in err_str)

                reason = "UnknownError"
                if is_rate_limit:
                    reason = "HTTP_429_RateLimit"
                elif is_forbidden:
                    reason = "HTTP_403_Forbidden"
                elif is_not_found:
                    reason = "HTTP_404_NotFound"
                elif is_server_error:
                    reason = "HTTP_5xx_ServerError"
                elif is_timeout:
                    reason = "Timeout"
                else:
                    reason = type(e).__name__

                self.record_error(reason)

                # 404 should not retry multiple times if resource does not exist
                if is_not_found:
                    raise e

                retries += 1
                fn_name = getattr(fn, "__name__", str(fn))
                if retries > self.max_retries:
                    logger.error(f"Max retries ({self.max_retries}) exceeded for {fn_name}: {reason}")
                    raise e

                if is_rate_limit or is_forbidden:
                    cooldown = self.cooldown_seconds + random.uniform(1.0, 5.0)
                    with self._lock:
                        self._cooldown_until = max(self._cooldown_until, time.time() + cooldown)
                    logger.warning(f"Hit {reason}. Cooldown for {cooldown:.1f}s before retry {retries}/{self.max_retries}...")
                    time.sleep(cooldown)
                    self.rotate_proxy()
                else:
                    backoff = (2.0 ** (retries - 1)) + random.uniform(self.jitter_min, max(self.jitter_min, self.jitter_max * 2.0))
                    logger.warning(f"Request failed ({reason}). Backoff {backoff:.1f}s before retry {retries}/{self.max_retries}...")
                    time.sleep(backoff)

# Singleton rate limiter instance
_global_limiter: Optional[RateLimiter] = None

def get_limiter() -> RateLimiter:
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter()
    return _global_limiter

def set_limiter(limiter: RateLimiter):
    global _global_limiter
    _global_limiter = limiter
