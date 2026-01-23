"""Cloudflare KV storage backend."""

from typing import Any


class CloudflareKVStore:
    """Cloudflare KV storage backend.

    Uses the Cloudflare KV API for key-value storage.
    """

    def __init__(
        self,
        namespace_id: str | None = None,
        api_token: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Cloudflare KV store.

        Args:
            namespace_id: KV namespace ID
            api_token: Cloudflare API token
            **kwargs: Ignored
        """
        if not namespace_id or not api_token:
            raise ValueError(
                "CloudflareKVStore requires namespace_id and api_token. "
                "Use 'memory' backend for development."
            )

        self.namespace_id = namespace_id
        self.api_token = api_token
        # TODO: Initialize httpx client for KV API

    async def get(self, key: str) -> bytes | None:
        """Get a value by key."""
        # TODO: Implement KV get via Cloudflare API
        raise NotImplementedError("KV backend not yet implemented")

    async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
        """Set a value with optional TTL in seconds."""
        # TODO: Implement KV set via Cloudflare API
        raise NotImplementedError("KV backend not yet implemented")

    async def delete(self, key: str) -> None:
        """Delete a key."""
        # TODO: Implement KV delete via Cloudflare API
        raise NotImplementedError("KV backend not yet implemented")

    async def list(self, prefix: str) -> list[str]:
        """List keys matching a prefix."""
        # TODO: Implement KV list via Cloudflare API
        raise NotImplementedError("KV backend not yet implemented")
