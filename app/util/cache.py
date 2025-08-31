from __future__ import annotations

from cachetools import TTLCache


def get_ttl_cache(maxsize: int = 256, ttl: int = 300) -> TTLCache:
    """Return a simple TTL cache instance with the given parameters."""
    return TTLCache(maxsize=maxsize, ttl=ttl)

