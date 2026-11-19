"""Tiny in-memory sliding-window limiter for sign-in attempts. One API process only (fine for a POC; use Redis to share it)."""

import time
from collections import defaultdict, deque

from .config import get_settings

_fails: dict[str, deque] = defaultdict(deque)


def _prune(q: deque, now: float, window: int) -> None:
    while q and now - q[0] > window:
        q.popleft()


def is_blocked(key: str) -> int:
    """Seconds until the key may try again, or 0."""
    s = get_settings()
    now = time.monotonic()
    q = _fails[key]
    _prune(q, now, s.login_window_seconds)
    if len(q) >= s.login_max_attempts:
        return int(s.login_window_seconds - (now - q[0])) + 1
    return 0


def record_failure(key: str) -> None:
    _fails[key].append(time.monotonic())


def reset(key: str) -> None:
    _fails.pop(key, None)


def clear_all() -> None:
    _fails.clear()
