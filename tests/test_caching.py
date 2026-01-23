"""Tests for caching module."""

import asyncio
import time

import pytest

from maven_core.caching import CachedLoader, CacheEntry, SingleFlight, TTLCache


class TestCacheEntry:
    """Tests for CacheEntry."""

    def test_is_expired_false_when_fresh(self) -> None:
        """Entry is not expired when TTL hasn't passed."""
        entry = CacheEntry(
            value="test",
            expires_at=time.time() + 100,
        )
        assert not entry.is_expired

    def test_is_expired_true_when_stale(self) -> None:
        """Entry is expired when TTL has passed."""
        entry = CacheEntry(
            value="test",
            expires_at=time.time() - 1,
        )
        assert entry.is_expired

    def test_ttl_remaining(self) -> None:
        """TTL remaining returns correct value."""
        entry = CacheEntry(
            value="test",
            expires_at=time.time() + 50,
        )
        assert 49 < entry.ttl_remaining <= 50


class TestTTLCache:
    """Tests for TTLCache."""

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self) -> None:
        """Get returns None for missing keys."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        result = await cache.get("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get(self) -> None:
        """Set and get work correctly."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        await cache.set("key", "value")
        result = await cache.get("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_expired_returns_none(self) -> None:
        """Expired entries return None."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=0)
        await cache.set("key", "value", ttl=0)
        # Wait a tiny bit for expiration
        await asyncio.sleep(0.01)
        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_or_set_caches_value(self) -> None:
        """Get or set caches the computed value."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        call_count = 0

        async def factory() -> str:
            nonlocal call_count
            call_count += 1
            return "computed"

        # First call computes
        result1 = await cache.get_or_set("key", factory)
        assert result1 == "computed"
        assert call_count == 1

        # Second call uses cache
        result2 = await cache.get_or_set("key", factory)
        assert result2 == "computed"
        assert call_count == 1  # Not incremented

    @pytest.mark.asyncio
    async def test_delete_removes_entry(self) -> None:
        """Delete removes entry from cache."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        await cache.set("key", "value")

        deleted = await cache.delete("key")
        assert deleted is True

        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_missing(self) -> None:
        """Delete returns False for missing keys."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        deleted = await cache.delete("missing")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_clear_removes_all(self) -> None:
        """Clear removes all entries."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60)
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")

        await cache.clear()

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None
        assert cache.size == 0

    @pytest.mark.asyncio
    async def test_max_size_eviction(self) -> None:
        """Cache evicts oldest when at max size."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60, max_size=3)

        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")
        await cache.set("key4", "value4")

        # Should have evicted oldest
        assert cache.size <= 3

    @pytest.mark.asyncio
    async def test_cleanup_expired(self) -> None:
        """Cleanup removes expired entries."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=0)
        await cache.set("key1", "value1", ttl=0)
        await cache.set("key2", "value2", ttl=60)

        await asyncio.sleep(0.01)
        removed = await cache.cleanup_expired()

        assert removed == 1
        assert await cache.get("key2") == "value2"


class TestSingleFlight:
    """Tests for SingleFlight."""

    @pytest.mark.asyncio
    async def test_single_call_executes(self) -> None:
        """Single call executes function."""
        sf = SingleFlight()
        call_count = 0

        async def fetch() -> str:
            nonlocal call_count
            call_count += 1
            return "result"

        result = await sf.do("key", fetch)

        assert result == "result"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_calls_deduplicated(self) -> None:
        """Concurrent calls with same key are deduplicated."""
        sf = SingleFlight()
        call_count = 0

        async def slow_fetch() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            return "result"

        # Start multiple concurrent calls
        results = await asyncio.gather(
            sf.do("key", slow_fetch),
            sf.do("key", slow_fetch),
            sf.do("key", slow_fetch),
        )

        assert all(r == "result" for r in results)
        assert call_count == 1  # Only one actual call

    @pytest.mark.asyncio
    async def test_different_keys_not_deduplicated(self) -> None:
        """Different keys are not deduplicated."""
        sf = SingleFlight()
        call_count = 0

        async def fetch() -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{call_count}"

        result1 = await sf.do("key1", fetch)
        result2 = await sf.do("key2", fetch)

        assert result1 == "result-1"
        assert result2 == "result-2"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_exception_propagates(self) -> None:
        """Exceptions propagate to all waiters."""
        sf = SingleFlight()

        async def failing_fetch() -> str:
            await asyncio.sleep(0.05)
            raise ValueError("test error")

        # All concurrent calls should receive the same exception
        with pytest.raises(ValueError, match="test error"):
            await asyncio.gather(
                sf.do("key", failing_fetch),
                sf.do("key", failing_fetch),
            )


class TestCachedLoader:
    """Tests for CachedLoader."""

    @pytest.mark.asyncio
    async def test_load_caches_result(self) -> None:
        """Load caches the result."""
        loader: CachedLoader[str] = CachedLoader(ttl_seconds=60)
        call_count = 0

        async def fetch() -> str:
            nonlocal call_count
            call_count += 1
            return "result"

        result1 = await loader.load("key", fetch)
        result2 = await loader.load("key", fetch)

        assert result1 == "result"
        assert result2 == "result"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_invalidate_removes_entry(self) -> None:
        """Invalidate removes cached entry."""
        loader: CachedLoader[str] = CachedLoader(ttl_seconds=60)
        call_count = 0

        async def fetch() -> str:
            nonlocal call_count
            call_count += 1
            return f"result-{call_count}"

        await loader.load("key", fetch)
        await loader.invalidate("key")
        result = await loader.load("key", fetch)

        assert result == "result-2"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_invalidate_prefix(self) -> None:
        """Invalidate prefix removes matching entries."""
        loader: CachedLoader[str] = CachedLoader(ttl_seconds=60)

        async def fetch(val: str) -> str:
            return val

        await loader.load("tenant:123:config", lambda: fetch("config1"))
        await loader.load("tenant:123:skills", lambda: fetch("skills1"))
        await loader.load("tenant:456:config", lambda: fetch("config2"))

        count = await loader.invalidate_prefix("tenant:123:")

        assert count == 2

    @pytest.mark.asyncio
    async def test_concurrent_loads_deduplicated(self) -> None:
        """Concurrent loads are deduplicated."""
        loader: CachedLoader[str] = CachedLoader(ttl_seconds=60)
        call_count = 0

        async def slow_fetch() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            return "result"

        results = await asyncio.gather(
            loader.load("key", slow_fetch),
            loader.load("key", slow_fetch),
            loader.load("key", slow_fetch),
        )

        assert all(r == "result" for r in results)
        assert call_count == 1
