"""Simple in-process sliding-window rate limiter.

A Redis-backed limiter can be substituted without changing API dependencies.
The default is intentionally dependency-free so demo deployments remain runnable.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self.limit = max(int(limit_per_minute), 1)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - 60.0
        with self._lock:
            q = self._hits[key]
            while q and q[0] < window_start:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] < now - 60.0:
                q.popleft()
            return max(self.limit - len(q), 0)
