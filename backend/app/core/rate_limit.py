"""In-process sliding-window rate limiting for webhook routes.

This is intentionally simple and process-local. A production deployment would use an API
gateway or shared Redis-backed limiter; the behavior and response contract stay the same.
"""

from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class SlidingWindowRateLimiter:
    def __init__(self, *, requests_per_minute: int, window_seconds: float = 60.0) -> None:
        self.limit = requests_per_minute
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> tuple[bool, int, int]:
        """Return ``(allowed, remaining, retry_after_seconds)``."""

        if self.limit <= 0:
            return True, self.limit, 0
        now = monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])) + 1)
                return False, 0, retry_after
            bucket.append(now)
            # Remove empty buckets opportunistically to keep the map bounded.
            if len(self._hits) > 2048:
                empty = [bucket_key for bucket_key, value in self._hits.items() if not value]
                for bucket_key in empty:
                    self._hits.pop(bucket_key, None)
            return True, max(0, self.limit - len(bucket)), 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
