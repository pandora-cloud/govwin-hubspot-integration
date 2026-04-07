"""Tests for the GovWin rate limiter."""


from src.govwin.rate_limiter import TokenBucketRateLimiter


def test_acquire_under_limit():
    limiter = TokenBucketRateLimiter(max_calls_per_hour=100, safety_margin=10)
    wait = limiter.acquire()
    assert wait == 0.0
    # acquire() is side-effect-free — no call recorded
    assert limiter.calls_in_window == 0
    # record explicitly
    limiter.record_call()
    assert limiter.calls_in_window == 1


def test_acquire_at_limit():
    limiter = TokenBucketRateLimiter(max_calls_per_hour=10, safety_margin=0)
    for _ in range(10):
        limiter.record_call()  # acquire is side-effect-free, use record_call

    # Next call should return a wait time
    wait = limiter.acquire()
    assert wait > 0


def test_can_proceed():
    limiter = TokenBucketRateLimiter(max_calls_per_hour=5, safety_margin=0)
    for _ in range(5):
        limiter.record_call()

    assert not limiter.can_proceed()


def test_status():
    limiter = TokenBucketRateLimiter(max_calls_per_hour=100, safety_margin=10)
    limiter.record_call(5)

    status = limiter.status()
    assert status.calls_made == 5
    assert status.calls_remaining == 85  # 100 - 10 (margin) - 5
    assert not status.is_limited


def test_reset():
    limiter = TokenBucketRateLimiter(max_calls_per_hour=100, safety_margin=0)
    limiter.record_call(50)
    assert limiter.calls_in_window == 50

    limiter.reset()
    assert limiter.calls_in_window == 0
