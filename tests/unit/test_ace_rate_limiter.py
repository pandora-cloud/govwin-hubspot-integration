"""Tests for the ACE rate limiter."""

from __future__ import annotations

import time
from unittest.mock import patch

from src.ace.rate_limiter import ACERateLimiter


def test_initial_capacity_allows_full_burst() -> None:
    limiter = ACERateLimiter(reads_per_sec=10, writes_per_sec=1)
    # All 10 reads available immediately, no sleep
    with patch("time.sleep") as sleep:
        for _ in range(10):
            limiter.acquire_read()
        sleep.assert_not_called()


def test_write_bucket_throttles_after_one_call() -> None:
    limiter = ACERateLimiter(writes_per_sec=1)
    limiter.acquire_write()  # consume the only write token
    with patch("time.sleep") as sleep:
        limiter.acquire_write()
        sleep.assert_called_once()
        # Should have been asked to wait approximately 1 second.
        wait_arg = sleep.call_args[0][0]
        assert 0.5 < wait_arg <= 1.0


def test_separate_buckets_for_read_and_write() -> None:
    limiter = ACERateLimiter(reads_per_sec=10, writes_per_sec=1)
    limiter.acquire_write()
    # Reads should be unaffected by exhausted write bucket.
    with patch("time.sleep") as sleep:
        limiter.acquire_read()
        sleep.assert_not_called()


def test_refill_after_elapsed_time() -> None:
    limiter = ACERateLimiter(writes_per_sec=2)
    limiter.acquire_write()
    limiter.acquire_write()
    # Advance time so a token refills.
    later = time.monotonic() + 1.0
    with patch("time.monotonic", return_value=later), patch("time.sleep") as sleep:
        limiter.acquire_write()
        sleep.assert_not_called()


def test_reset_restores_full_capacity() -> None:
    limiter = ACERateLimiter(writes_per_sec=1)
    limiter.acquire_write()
    limiter.reset()
    with patch("time.sleep") as sleep:
        limiter.acquire_write()
        sleep.assert_not_called()
