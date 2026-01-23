"""TTL-based caching with single-flight deduplication.

Provides in-memory caching with configurable TTL and protection against
cache stampedes via single-flight deduplication.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, TypeVar

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
    """Thread-safe TTL cache with optional stale-while-revalidate.

    Example:
        cache = TTLCache[str](ttl_seconds=300)
        await cache.set("key", "value")
        value = await cache.get("key")
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
        self._lock = asyncio.Lock()

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
            # Truly expired
            del self._cache[key]
            return None
        return entry.value

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[T]],
    ) -> T:
        """Get value from cache or compute and store it.

        Uses single-flight to prevent cache stampedes.

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

        # Need to compute - use single-flight
        async with self._lock:
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
        async with self._lock:
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
        for key in sorted_keys[:evict_count]:
            del self._cache[key]

    async def delete(self, key: str) -> bool:
        """Delete a key from cache.

        Returns True if key existed.
        """
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def clear(self) -> None:
        """Clear all entries."""
        async with self._lock:
            self._cache.clear()

    async def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns number of entries removed.
        """
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


class SingleFlight:
    """Deduplicates concurrent calls to the same function with the same key.

    Prevents cache stampedes by ensuring only one call per key is in-flight
    at a time. Other callers wait for the result of the first call.

    Example:
        sf = SingleFlight()

        async def expensive_fetch(key: str) -> dict:
            return await sf.do(key, lambda: fetch_from_api(key))
    """

    def __init__(self) -> None:
        """Initialize single-flight handler."""
        self._in_flight: dict[str, asyncio.Future[Any]] = {}
        self._lock = asyncio.Lock()

    async def do(
        self,
        key: str,
        func: Callable[[], Awaitable[T]],
    ) -> T:
        """Execute function, deduplicating concurrent calls.

        If another call with the same key is in progress, waits for
        that result instead of executing again.

        Args:
            key: Unique key for this operation
            func: Async function to execute

        Returns:
            Result from func (may be from another caller)
        """
        async with self._lock:
            if key in self._in_flight:
                # Another call in progress - wait for it
                future = self._in_flight[key]
            else:
                # First caller - create future and execute
                future = asyncio.get_event_loop().create_future()
                self._in_flight[key] = future

                # Execute in background, don't hold lock
                asyncio.create_task(self._execute(key, func, future))

        # Wait for result (outside lock)
        return await future

    async def _execute(
        self,
        key: str,
        func: Callable[[], Awaitable[T]],
        future: asyncio.Future[T],
    ) -> None:
        """Execute function and set result on future."""
        try:
            result = await func()
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)
        finally:
            async with self._lock:
                self._in_flight.pop(key, None)


class CachedLoader(Generic[T]):
    """Combines caching with single-flight loading.

    Provides a simple interface for loading and caching resources
    with automatic deduplication and TTL expiration.

    Example:
        loader = CachedLoader(ttl_seconds=300)

        async def get_config(tenant_id: str) -> Config:
            return await loader.load(
                f"config:{tenant_id}",
                lambda: fetch_config(tenant_id)
            )
    """

    def __init__(
        self,
        ttl_seconds: int = 300,
        max_size: int = 1000,
    ) -> None:
        """Initialize cached loader.

        Args:
            ttl_seconds: Cache TTL in seconds
            max_size: Maximum cache entries
        """
        self._cache: TTLCache[T] = TTLCache(
            ttl_seconds=ttl_seconds,
            max_size=max_size,
        )
        self._single_flight = SingleFlight()

    async def load(
        self,
        key: str,
        loader: Callable[[], Awaitable[T]],
    ) -> T:
        """Load a resource, using cache and single-flight.

        Args:
            key: Cache key
            loader: Function to load if not cached

        Returns:
            Cached or newly loaded value
        """
        # Check cache first
        cached = await self._cache.get(key)
        if cached is not None:
            return cached

        # Use single-flight to load
        async def load_and_cache() -> T:
            value = await loader()
            await self._cache.set(key, value)
            return value

        return await self._single_flight.do(key, load_and_cache)

    async def invalidate(self, key: str) -> bool:
        """Invalidate a cached entry.

        Returns True if entry existed.
        """
        return await self._cache.delete(key)

    async def invalidate_prefix(self, prefix: str) -> int:
        """Invalidate all entries with given prefix.

        Returns number of entries invalidated.
        """
        count = 0
        keys_to_delete = [
            key for key in self._cache._cache.keys()
            if key.startswith(prefix)
        ]
        for key in keys_to_delete:
            if await self._cache.delete(key):
                count += 1
        return count

    async def clear(self) -> None:
        """Clear all cached entries."""
        await self._cache.clear()
