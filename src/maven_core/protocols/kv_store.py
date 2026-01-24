"""KVStore protocol for key-value storage backends."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class KVStore(Protocol):
    """Protocol for key-value storage backends (KV, Redis, DynamoDB)."""

    async def get(self, key: str) -> bytes | None:
        """Get a value by key. Returns None if not found."""
        ...

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set a value with optional TTL in seconds."""
        ...

    async def delete(self, key: str) -> None:
        """Delete a key. No-op if key doesn't exist."""
        ...

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix."""
        ...
