"""TTL-based caching with stampede protection.

Provides in-memory caching with configurable TTL and protection against
cache stampedes via lock-based deduplication.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """A cached value with expiration metadata."""

    value: T
    expires_at: float
    created_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        """Check if the entry has expired."""
        return time.time() > self.expires_at

    @property
    def ttl_remaining(self) -> float:
        """Get remaining TTL in seconds."""
        remaining = self.expires_at - time.time()
        return max(0, remaining)


class TTLCache(Generic[T]):
    """Thread-safe TTL cache with stampede protection.

    Example:
        cache = TTLCache[str](ttl_seconds=300)
        await cache.set("key", "value")
        value = await cache.get("key")

        # Or use get_or_set for atomic cache-or-compute:
        value = await cache.get_or_set("key", lambda: fetch_from_api())
    """

    def __init__(
        self,
        ttl_seconds: int = 300,
        stale_ttl_seconds: int | None = None,
        max_size: int = 1000,
    ) -> None:
        """Initialize cache.

        Args:
            ttl_seconds: Time-to-live for cache entries
            stale_ttl_seconds: Optional stale TTL for stale-while-revalidate pattern
            max_size: Maximum number of entries before eviction
        """
        self.ttl_seconds = ttl_seconds
        self.stale_ttl_seconds = stale_ttl_seconds
        self.max_size = max_size
        self._cache: dict[str, CacheEntry[T]] = {}
        self._cache_lock = asyncio.Lock()  # For cache mutations
        self._key_locks: dict[str, asyncio.Lock] = {}  # Per-key locks for get_or_set
        self._locks_lock = asyncio.Lock()  # For managing key locks

    async def _get_key_lock(self, key: str) -> asyncio.Lock:
        """Get or create a lock for a specific key."""
        async with self._locks_lock:
            if key not in self._key_locks:
                self._key_locks[key] = asyncio.Lock()
            return self._key_locks[key]

    async def get(self, key: str) -> T | None:
        """Get a value from cache.

        Returns None if not found or expired.
        """
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            # If stale-while-revalidate and within stale window
            if self.stale_ttl_seconds:
                stale_expires = entry.expires_at + self.stale_ttl_seconds
                if time.time() <= stale_expires:
                    return entry.value
            # Truly expired - clean up cache entry
            del self._cache[key]
            # Note: Per-key lock cleanup is deferred since we're in a sync context.
            # Locks are cleaned up during cleanup_expired(), delete(), or _evict_oldest().
            return None
        return entry.value

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[T]],
    ) -> T:
        """Get value from cache or compute and store it.

        Uses per-key locking to prevent cache stampedes - only one caller
        computes the value while others wait for the same key.

        Args:
            key: Cache key
            factory: Async function to compute value if not cached

        Returns:
            Cached or newly computed value
        """
        # Check cache first (without lock for reads)
        value = await self.get(key)
        if value is not None:
            return value

        # Need to compute - use per-key lock to prevent stampede
        key_lock = await self._get_key_lock(key)
        async with key_lock:
            # Double-check after acquiring lock
            value = await self.get(key)
            if value is not None:
                return value

            # Compute value
            value = await factory()
            await self._set_internal(key, value)
            return value

    async def set(self, key: str, value: T, ttl: int | None = None) -> None:
        """Set a value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Optional TTL override
        """
        async with self._cache_lock:
            await self._set_internal(key, value, ttl)

    async def _set_internal(self, key: str, value: T, ttl: int | None = None) -> None:
        """Internal set without lock (caller must hold lock)."""
        # Evict if at capacity
        if len(self._cache) >= self.max_size and key not in self._cache:
            await self._evict_oldest()

        ttl_seconds = ttl if ttl is not None else self.ttl_seconds
        self._cache[key] = CacheEntry(
            value=value,
            expires_at=time.time() + ttl_seconds,
        )

    async def _evict_oldest(self) -> None:
        """Evict oldest entries to make room."""
        if not self._cache:
            return

        # Sort by creation time, evict oldest 10%
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: self._cache[k].created_at,
        )
        evict_count = max(1, len(sorted_keys) // 10)
        evicted_keys = sorted_keys[:evict_count]
        for key in evicted_keys:
            del self._cache[key]

        # Clean up per-key locks for evicted keys
        async with self._locks_lock:
            for key in evicted_keys:
                self._key_locks.pop(key, None)

    async def delete(self, key: str) -> bool:
        """Delete a key from cache.

        Returns True if key existed.
        """
        async with self._cache_lock:
            if key in self._cache:
                del self._cache[key]
                # Clean up per-key lock
                async with self._locks_lock:
                    self._key_locks.pop(key, None)
                return True
            return False

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all entries with given prefix.

        Returns number of entries deleted.
        """
        async with self._cache_lock:
            keys_to_delete = [
                key for key in self._cache.keys()
                if key.startswith(prefix)
            ]
            for key in keys_to_delete:
                del self._cache[key]
            # Clean up per-key locks
            async with self._locks_lock:
                for key in keys_to_delete:
                    self._key_locks.pop(key, None)
            return len(keys_to_delete)

    async def clear(self) -> None:
        """Clear all entries."""
        async with self._cache_lock:
            self._cache.clear()
            async with self._locks_lock:
                self._key_locks.clear()

    async def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns number of entries removed.
        """
        async with self._cache_lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired
            ]
            for key in expired_keys:
                del self._cache[key]
            # Clean up per-key locks for expired keys
            async with self._locks_lock:
                for key in expired_keys:
                    self._key_locks.pop(key, None)
            return len(expired_keys)

    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)
