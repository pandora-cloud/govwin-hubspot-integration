"""Token bucket rate limiter for GovWin API (4,000 calls/hour rolling window)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RateLimitStatus:
    """Current state of the rate limiter."""

    calls_made: int
    calls_remaining: int
    window_resets_in_seconds: float
    is_limited: bool


class TokenBucketRateLimiter:
    """Rolling-window rate limiter tracking calls within a 60-minute window."""

    def __init__(
        self,
        max_calls_per_hour: int = 4000,
        safety_margin: int = 100,
    ) -> None:
        self._max_calls = max_calls_per_hour
        self._safety_margin = safety_margin
        self._effective_limit = max_calls_per_hour - safety_margin
        self._call_timestamps: list[float] = []
        self._window_seconds = 3600  # 60 minutes

    def _prune_old_calls(self) -> None:
        """Remove timestamps older than the rolling window."""
        cutoff = time.time() - self._window_seconds
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]

    def acquire(self, count: int = 1) -> float:
        """Check if request(s) can proceed. Returns wait time in seconds.

        This method has NO side effects -- it does not record the request.
        Call ``record_call()`` separately after the request completes.
        """
        self._prune_old_calls()

        if len(self._call_timestamps) + count <= self._effective_limit:
            return 0.0

        # Calculate how long to wait for enough tokens to free up
        if self._call_timestamps:
            oldest_in_window = self._call_timestamps[0]
            wait_time = oldest_in_window + self._window_seconds - time.time() + 1
            return max(wait_time, 1.0)

        return 60.0  # Fallback wait

    def record_call(self, count: int = 1) -> None:
        """Record that API calls were made (for external tracking)."""
        now = time.time()
        self._call_timestamps.extend([now] * count)

    def status(self) -> RateLimitStatus:
        """Get current rate limit status."""
        self._prune_old_calls()
        calls_made = len(self._call_timestamps)
        calls_remaining = max(0, self._effective_limit - calls_made)

        window_resets_in = 0.0
        if self._call_timestamps:
            oldest = self._call_timestamps[0]
            window_resets_in = max(0.0, oldest + self._window_seconds - time.time())

        return RateLimitStatus(
            calls_made=calls_made,
            calls_remaining=calls_remaining,
            window_resets_in_seconds=window_resets_in,
            is_limited=calls_remaining == 0,
        )

    def can_proceed(self, count: int = 1) -> bool:
        """Check if a request can proceed without waiting."""
        self._prune_old_calls()
        return len(self._call_timestamps) + count <= self._effective_limit

    @property
    def calls_in_window(self) -> int:
        """Number of calls made in the current rolling window."""
        self._prune_old_calls()
        return len(self._call_timestamps)

    def reset(self) -> None:
        """Reset the rate limiter (for testing)."""
        self._call_timestamps.clear()
