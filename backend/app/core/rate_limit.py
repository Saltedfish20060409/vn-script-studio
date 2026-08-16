"""Simple in-process rate limiting for auth endpoints.

Per-IP sliding-window counters. In-process only: fine for single-worker
deployments; multi-worker setups should move this to Redis or a proxy.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

# key -> (window_start, deque of event timestamps)
_hits: Dict[str, Deque[float]] = defaultdict(deque)
_WINDOW = 60.0


def _key(ip: Optional[str], kind: str) -> str:
    return f"{kind}:{ip or 'unknown'}"


def check_rate(
    ip: Optional[str],
    kind: str,
    limit: int,
    *,
    enabled: bool = True,
) -> bool:
    """Return True when the request is allowed (under the limit)."""
    if not enabled:
        return True
    now = time.monotonic()
    key = _key(ip, kind)
    q = _hits[key]
    while q and q[0] < now - _WINDOW:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    # Lazy cleanup of stale keys.
    if len(_hits) > 10_000:
        for k in [k for k, v in _hits.items() if not v or v[-1] < now - _WINDOW * 2]:
            _hits.pop(k, None)
    return True
