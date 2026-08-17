"""Simple in-memory TTL cache for throttling expensive recurring operations.

Used to avoid running purge/cleanup/ensure-defaults queries on every single
API request. These operations only need to run periodically (e.g. once per
minute), not on every request.
"""
import time
from typing import Any

_cache: dict[str, float] = {}
_value_cache: dict[str, tuple[float, Any]] = {}


def should_run(key: str, ttl_seconds: float) -> bool:
    """Return True if the operation hasn't run in the last ttl_seconds.

    Side effect: updates the timestamp so the next call within the TTL
    window returns False.
    """
    now = time.monotonic()
    last = _cache.get(key)
    if last is not None and (now - last) < ttl_seconds:
        return False
    _cache[key] = now
    return True


def get_cached_value(key: str, ttl_seconds: float) -> Any | None:
    """Return cached value if still fresh, else None."""
    entry = _value_cache.get(key)
    if entry is None:
        return None
    ts, val = entry
    if (time.monotonic() - ts) < ttl_seconds:
        return val
    return None


def set_cached_value(key: str, value: Any) -> None:
    """Store a value with current timestamp."""
    _value_cache[key] = (time.monotonic(), value)
