"""Per-IP rate limits for the account endpoints: sliding windows, in memory, generous for a
home server behind one proxy. A limited request answers 429 with the seconds to wait.

Buckets: invite creation, passkey registration and login. Each counts requests, so a login
(options + verify) is two hits.
"""

from __future__ import annotations

import threading
import time
from collections import deque

# bucket: (hits, seconds)
DEFAULT_LIMITS: dict[str, tuple[int, int]] = {
    "invite": (30, 3600),  # invites made per hour
    "register": (40, 3600),  # 20 sign-ups per hour (two requests each)
    "login": (120, 900),  # 60 logins per quarter hour (two requests each)
}


class RateLimiter:
    def __init__(self, limits: dict[str, tuple[int, int]] | None = None):
        self.limits = dict(DEFAULT_LIMITS if limits is None else limits)
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str, now: float | None = None) -> int:
        """Count one request from `key` in `bucket`. Returns 0 when it is allowed, else the
        whole seconds until the oldest counted request leaves the window (the request is
        not counted then: a blocked client doesn't push its own wait out)."""
        spec = self.limits.get(bucket)
        if spec is None:
            return 0
        limit, window = spec
        now = time.time() if now is None else now
        with self._lock:
            q = self._hits.setdefault((bucket, key), deque())
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(q[0] + window - now) + 1)
            q.append(now)
            if len(self._hits) > 10000:  # a flood of addresses: forget the idle ones
                for k in [k for k, v in self._hits.items() if not v or v[-1] <= now - window]:
                    del self._hits[k]
        return 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
