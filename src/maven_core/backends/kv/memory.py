"""In-memory key-value storage."""

import asyncio
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    """A cached value with optional expiration."""

    value: bytes
    expires_at: float | None = None

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class MemoryKVStore:
    """In-memory key-value store.

    Suitable for development and testing. Data is lost on restart.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize memory KV store.

        Args:
            **kwargs: Ignored (for compatibility with other backends)
        """
        self._data: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        """Get a value by key."""
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                del self._data[key]
                return None
            return entry.value

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set a value with optional TTL in seconds."""
        expires_at = time.time() + ttl if ttl else None
        async with self._lock:
            self._data[key] = CacheEntry(value=value, expires_at=expires_at)

    async def delete(self, key: str) -> None:
        """Delete a key."""
        async with self._lock:
            self._data.pop(key, None)

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix."""
        async with self._lock:
            # Clean up expired entries first
            expired = [k for k, v in self._data.items() if v.is_expired()]
            for k in expired:
                del self._data[k]

            return [k for k in self._data if k.startswith(prefix)]

    async def clear(self) -> None:
        """Clear all data. Useful for testing."""
        async with self._lock:
            self._data.clear()
