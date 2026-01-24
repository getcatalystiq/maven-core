"""Tests for caching module."""

import asyncio
import time

import pytest

from maven_core.caching import CacheEntry, TTLCache


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


