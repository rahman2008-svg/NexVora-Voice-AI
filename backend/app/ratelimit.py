"""Small in-memory sliding-window limiter (per process).
For multi-worker deployments put a shared limiter (e.g. at your reverse proxy) in front."""
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._calls = 0

    def check(self, key: str, now: Optional[float] = None) -> Tuple[bool, int]:
        """Record an event. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._calls += 1
            if self._calls % 500 == 0:  # opportunistic cleanup of idle keys
                for k in [k for k, q in self._events.items() if not q or now - q[-1] > self.window]:
                    del self._events[k]
            q = self._events[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.max_events:
                return False, max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            return True, 0
