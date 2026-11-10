import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Small in-memory sliding-window limiter (per process)."""

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self.hits) > 5000:  # keep memory bounded
                for k in [k for k, v in self.hits.items() if not v or v[-1] <= now - self.window][:1000]:
                    self.hits.pop(k, None)
            return True


api_limiter = RateLimiter(limit=120, window=60)
public_limiter = RateLimiter(limit=60, window=60)
