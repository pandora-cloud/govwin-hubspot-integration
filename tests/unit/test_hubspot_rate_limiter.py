"""Tests for HubSpot sliding-window rate limiter."""

from __future__ import annotations

import time

from src.hubspot.rate_limiter import HubSpotRateLimiter


class TestAcquire:
    def test_acquire_no_side_effect(self):
        """Call acquire() and verify _timestamps is still empty (no side effects)."""
        limiter = HubSpotRateLimiter(max_requests=100, buffer=10)
        wait = limiter.acquire()
        assert wait == 0.0
        # acquire() should NOT record the request
        assert len(limiter._timestamps) == 0

    def test_acquire_returns_zero_when_empty(self):
        """Verify 0.0 on fresh limiter."""
        limiter = HubSpotRateLimiter(max_requests=100, buffer=10)
        assert limiter.acquire() == 0.0

    def test_acquire_returns_wait_when_full(self):
        """Fill up limiter and verify wait > 0."""
        limiter = HubSpotRateLimiter(max_requests=10, buffer=0, window_seconds=10.0)
        # Fill the limiter
        now = time.time()
        limiter._timestamps = [now] * 10

        wait = limiter.acquire()
        assert wait > 0


class TestRecord:
    def test_record_adds_timestamp(self):
        """Call record() and verify _timestamps has one entry."""
        limiter = HubSpotRateLimiter(max_requests=100, buffer=10)
        assert len(limiter._timestamps) == 0
        limiter.record()
        assert len(limiter._timestamps) == 1


class TestWaitIfNeeded:
    def test_wait_if_needed_records_once(self):
        """Call wait_if_needed() and verify exactly 1 timestamp added (no double-count)."""
        limiter = HubSpotRateLimiter(max_requests=100, buffer=10)
        limiter.wait_if_needed()
        # wait_if_needed calls acquire() (no side effect) + record() (1 timestamp)
        assert len(limiter._timestamps) == 1
