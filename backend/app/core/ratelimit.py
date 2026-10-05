"""Per-user (or per-IP) rate limits for expensive endpoints: AI calls, model fitting, uploads.

In-memory sliding window: right for a single API process. Behind several instances, put the
same limits in the load balancer / API gateway (e.g. AWS WAF rate-based rules) instead.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from .config import get_settings

ENABLED = get_settings().rate_limit_enabled
_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def reset() -> None:
    with _lock:
        _hits.clear()


def check(key: str, limit: int, window_s: float = 60.0) -> None:
    if not ENABLED:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(window_s - (now - q[0])))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Too many requests. Please wait {retry} s and try again.",
                headers={"Retry-After": str(retry)},
            )
        q.append(now)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
