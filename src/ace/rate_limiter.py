"""Token bucket rate limiter for the AWS Partner Central Selling API.

AWS publishes two per-account buckets:

* Reads: 10/sec, 100,000/24h (GetOpportunity, ListOpportunities, etc.)
* Writes: 1/sec, 10,000/24h (CreateOpportunity, UpdateOpportunity, etc.)

Throttled calls return ``ThrottlingException``. The standard recovery is
exponential backoff (handled in the client via tenacity); this limiter is a
proactive guard so we do not burn the per-second bucket on bursts.
"""

from __future__ import annotations

import logging
import time
from threading import Lock

logger = logging.getLogger(__name__)


class ACERateLimiter:
    """Per-second token bucket with separate read and write buckets."""

    def __init__(
        self,
        reads_per_sec: int = 10,
        writes_per_sec: int = 1,
    ) -> None:
        self._read_capacity = reads_per_sec
        self._write_capacity = writes_per_sec
        self._read_tokens: float = float(reads_per_sec)
        self._write_tokens: float = float(writes_per_sec)
        self._last_refill = time.monotonic()
        self._lock = Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._read_tokens = min(
            self._read_capacity, self._read_tokens + elapsed * self._read_capacity
        )
        self._write_tokens = min(
            self._write_capacity, self._write_tokens + elapsed * self._write_capacity
        )
        self._last_refill = now

    def _consume(self, *, write: bool) -> float:
        """Return seconds the caller should sleep before the call.

        Refills first, then either consumes a token (returns 0.0) or computes
        how long until one will be available.
        """
        with self._lock:
            self._refill()
            if write:
                if self._write_tokens >= 1.0:
                    self._write_tokens -= 1.0
                    return 0.0
                missing = 1.0 - self._write_tokens
                return missing / self._write_capacity
            if self._read_tokens >= 1.0:
                self._read_tokens -= 1.0
                return 0.0
            missing = 1.0 - self._read_tokens
            return missing / self._read_capacity

    def acquire_read(self) -> None:
        wait = self._consume(write=False)
        if wait > 0:
            logger.debug("ace rate-limiter: sleeping %.3fs for read token", wait)
            time.sleep(wait)
            with self._lock:
                self._refill()
                self._read_tokens = max(0.0, self._read_tokens - 1.0)

    def acquire_write(self) -> None:
        wait = self._consume(write=True)
        if wait > 0:
            logger.debug("ace rate-limiter: sleeping %.3fs for write token", wait)
            time.sleep(wait)
            with self._lock:
                self._refill()
                self._write_tokens = max(0.0, self._write_tokens - 1.0)

    def reset(self) -> None:
        """Reset the limiter (for tests)."""
        with self._lock:
            self._read_tokens = float(self._read_capacity)
            self._write_tokens = float(self._write_capacity)
            self._last_refill = time.monotonic()
