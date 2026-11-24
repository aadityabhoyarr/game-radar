import time
import pytest
from radar.limiter import RateLimiter

def test_rate_limiter_interval():
    # Test min interval enforced
    limiter = RateLimiter(max_rps=10.0, jitter_min=0.01, jitter_max=0.02)
    start = time.time()
    for _ in range(3):
        limiter.call(lambda: True)
    elapsed = time.time() - start
    assert elapsed >= 0.2

def test_rate_limiter_retry_and_backoff():
    limiter = RateLimiter(max_rps=100.0, jitter_min=0.0, jitter_max=0.0, max_retries=2)
    attempts = 0

    def faulty():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise ConnectionError("Temporary glitch")
        return "success"

    res = limiter.call(faulty)
    assert res == "success"
    assert attempts == 2
    assert limiter.failure_count == 1

def test_rate_limiter_exceed_retries():
    limiter = RateLimiter(max_rps=100.0, jitter_min=0.0, jitter_max=0.0, max_retries=2)

    def always_fails():
        raise ValueError("Unrecoverable error")

    with pytest.raises(ValueError):
        limiter.call(always_fails)
    assert limiter.failure_count == 3
