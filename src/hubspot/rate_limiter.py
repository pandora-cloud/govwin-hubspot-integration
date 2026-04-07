"""Sliding window rate limiter for HubSpot API (100 requests/10 seconds)."""

from __future__ import annotations

import time


class HubSpotRateLimiter:
    """Sliding window rate limiter for HubSpot's 100 req/10s limit."""

    def __init__(
        self, max_requests: int = 100, window_seconds: float = 10.0, buffer: int = 10
    ) -> None:
        self._max_requests = max_requests - buffer
        self._window_seconds = window_seconds
        self._timestamps: list[float] = []

    def _prune(self) -> None:
        cutoff = time.time() - self._window_seconds
        self._timestamps = [t for t in self._timestamps if t > cutoff]

    def acquire(self) -> float:
        """Returns wait time in seconds. 0 means proceed immediately.

        This method has NO side effects -- it does not record the request.
        Call ``record()`` separately after the request is made.
        """
        self._prune()
        if len(self._timestamps) < self._max_requests:
            return 0.0

        oldest = self._timestamps[0]
        wait = oldest + self._window_seconds - time.time() + 0.1
        return max(wait, 0.1)

    def record(self) -> None:
        """Record that a request was made at the current time."""
        self._timestamps.append(time.time())

    def wait_if_needed(self) -> None:
        """Block until a request can proceed, then record it."""
        wait = self.acquire()
        if wait > 0:
            time.sleep(wait)
        self.record()
