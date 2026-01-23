"""Tests for in-memory KV storage backend."""

import asyncio

import pytest

from maven_core.backends.kv.memory import MemoryKVStore


@pytest.fixture
def kv_store():
    """Create a memory KV store."""
    return MemoryKVStore()


class TestMemoryKVStore:
    """Tests for MemoryKVStore."""

    @pytest.mark.asyncio
    async def test_set_and_get(self, kv_store):
        """Test setting and getting a value."""
        await kv_store.set("key", b"value")
        result = await kv_store.get("key")
        assert result == b"value"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, kv_store):
        """Test getting a key that doesn't exist."""
        result = await kv_store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, kv_store):
        """Test deleting a key."""
        await kv_store.set("key", b"value")
        await kv_store.delete("key")
        result = await kv_store.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, kv_store):
        """Test deleting a key that doesn't exist (should not raise)."""
        await kv_store.delete("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_list(self, kv_store):
        """Test listing keys by prefix."""
        await kv_store.set("prefix:key1", b"value1")
        await kv_store.set("prefix:key2", b"value2")
        await kv_store.set("other:key3", b"value3")

        keys = await kv_store.list("prefix:")
        assert len(keys) == 2
        assert "prefix:key1" in keys
        assert "prefix:key2" in keys

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, kv_store):
        """Test that TTL causes expiration."""
        await kv_store.set("key", b"value", ttl=1)

        # Should be available immediately
        result = await kv_store.get("key")
        assert result == b"value"

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Should be expired now
        result = await kv_store.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite(self, kv_store):
        """Test overwriting a value."""
        await kv_store.set("key", b"value1")
        await kv_store.set("key", b"value2")
        result = await kv_store.get("key")
        assert result == b"value2"

    @pytest.mark.asyncio
    async def test_clear(self, kv_store):
        """Test clearing all data."""
        await kv_store.set("key1", b"value1")
        await kv_store.set("key2", b"value2")
        await kv_store.clear()

        assert await kv_store.get("key1") is None
        assert await kv_store.get("key2") is None
