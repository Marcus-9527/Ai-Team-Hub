"""
AI Team Hub — in-memory cache layer.

Strategy:
- TTL-based cache for read-heavy endpoints (teammates, channels, apikeys)
- Write-through invalidation on mutations
- Per-entity cache keys for fine-grained control
"""
import time
import threading
from collections import OrderedDict
from typing import Any, Optional, Callable


class TTLCache:
    """Thread-safe TTL cache with max size (LRU eviction)."""

    def __init__(self, maxsize: int = 256, ttl: int = 60):
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._store:
                value, ts = self._store[key]
                if time.time() - ts < self._ttl:
                    self._store.move_to_end(key)
                    self._hits += 1
                    return value
                else:
                    del self._store[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, time.time())
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        with self._lock:
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self._hits / total * 100:.1f}%" if total > 0 else "N/A",
            "size": len(self._store),
            "maxsize": self._maxsize,
            "ttl": self._ttl,
        }


# ── Global cache instances ──
teammate_cache = TTLCache(maxsize=128, ttl=60)
channel_cache = TTLCache(maxsize=64, ttl=60)
apikey_cache = TTLCache(maxsize=64, ttl=120)
message_cache = TTLCache(maxsize=32, ttl=30)


def cached_get(cache: TTLCache, key: str, fetch_fn: Callable) -> Any:
    """Get from cache or fetch and store."""
    result = cache.get(key)
    if result is not None:
        return result
    result = fetch_fn()
    if result is not None:
        cache.set(key, result)
    return result
