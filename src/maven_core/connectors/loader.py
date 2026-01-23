"""Connector loading and management."""

import json
from dataclasses import dataclass
from typing import Any

from maven_core.protocols import FileStore, KVStore
from maven_core.protocols.connector import ConnectorConfig, ConnectorCredentials
from maven_core.connectors.oauth import OAuthConfig, OAuthManager


@dataclass
class ConnectorIndex:
    """Cached connector metadata."""

    connectors: dict[str, ConnectorConfig]
    built_at: float


class ConnectorLoader:
    """Loads and manages connectors with OAuth support."""

    def __init__(
        self,
        files: FileStore,
        kv: KVStore,
        tenant_id: str,
        cache_ttl: int = 300,
    ) -> None:
        """Initialize connector loader.

        Args:
            files: File storage backend
            kv: KV storage backend
            tenant_id: Current tenant ID
            cache_ttl: Cache TTL in seconds
        """
        self.files = files
        self.kv = kv
        self.tenant_id = tenant_id
        self.cache_ttl = cache_ttl
        self.oauth_manager = OAuthManager(kv, tenant_id)
        self._local_cache: ConnectorIndex | None = None

    def _connectors_prefix(self) -> str:
        """Get storage prefix for connectors."""
        return f"connectors/{self.tenant_id}/"

    def _index_key(self) -> str:
        """Get KV key for connector index."""
        return f"connector_index:{self.tenant_id}"

    async def _get_index(self) -> ConnectorIndex:
        """Get connector index, using cache if available."""
        import time

        now = time.time()

        # Check local cache
        if self._local_cache and (now - self._local_cache.built_at) < self.cache_ttl:
            return self._local_cache

        # Check KV cache
        cached = await self.kv.get(self._index_key())
        if cached:
            try:
                data = json.loads(cached.decode())
                if (now - data.get("built_at", 0)) < self.cache_ttl:
                    connectors = {}
                    for name, cfg in data.get("connectors", {}).items():
                        connectors[name] = ConnectorConfig(
                            name=cfg["name"],
                            description=cfg["description"],
                            connector_type=cfg["connector_type"],
                            base_url=cfg.get("base_url"),
                            oauth_config=cfg.get("oauth_config"),
                            api_key_header=cfg.get("api_key_header"),
                            metadata=cfg.get("metadata", {}),
                        )
                    self._local_cache = ConnectorIndex(
                        connectors=connectors,
                        built_at=data.get("built_at", now),
                    )
                    return self._local_cache
            except (json.JSONDecodeError, KeyError):
                pass

        # Rebuild index
        return await self.rebuild_index()

    async def rebuild_index(self) -> ConnectorIndex:
        """Rebuild connector index from storage."""
        import time

        connectors: dict[str, ConnectorConfig] = {}
        prefix = self._connectors_prefix()

        async for meta in self.files.list(prefix):
            if not meta.key.endswith(".json"):
                continue

            # Extract name from key
            name = meta.key[len(prefix):-5]  # Remove prefix and .json
            if "/" in name:
                continue  # Skip nested files

            # Load connector config
            result = await self.files.get(meta.key)
            if result:
                content, _ = result
                try:
                    cfg = json.loads(content.decode())
                    connectors[name] = ConnectorConfig(
                        name=cfg.get("name", name),
                        description=cfg.get("description", ""),
                        connector_type=cfg.get("connector_type", "oauth"),
                        base_url=cfg.get("base_url"),
                        oauth_config=cfg.get("oauth_config"),
                        api_key_header=cfg.get("api_key_header"),
                        metadata=cfg.get("metadata", {}),
                    )
                except json.JSONDecodeError:
                    continue

        now = time.time()
        index = ConnectorIndex(connectors=connectors, built_at=now)

        # Cache in KV
        cache_data = {
            "connectors": {
                name: {
                    "name": cfg.name,
                    "description": cfg.description,
                    "connector_type": cfg.connector_type,
                    "base_url": cfg.base_url,
                    "oauth_config": cfg.oauth_config,
                    "api_key_header": cfg.api_key_header,
                    "metadata": cfg.metadata,
                }
                for name, cfg in connectors.items()
            },
            "built_at": now,
        }
        await self.kv.set(
            self._index_key(),
            json.dumps(cache_data).encode(),
            ttl=self.cache_ttl,
        )

        self._local_cache = index
        return index

    async def list_connectors(self) -> list[ConnectorConfig]:
        """List all configured connectors.

        Returns:
            List of connector configurations
        """
        index = await self._get_index()
        return list(index.connectors.values())

    async def get_connector(self, name: str) -> ConnectorConfig | None:
        """Get a connector configuration by name.

        Args:
            name: Connector name

        Returns:
            Connector configuration or None
        """
        index = await self._get_index()
        return index.connectors.get(name)

    async def save_connector(self, config: ConnectorConfig) -> None:
        """Save a connector configuration.

        Args:
            config: Connector configuration to save
        """
        key = f"{self._connectors_prefix()}{config.name}.json"
        data = {
            "name": config.name,
            "description": config.description,
            "connector_type": config.connector_type,
            "base_url": config.base_url,
            "oauth_config": config.oauth_config,
            "api_key_header": config.api_key_header,
            "metadata": config.metadata,
        }
        await self.files.put(
            key,
            json.dumps(data, indent=2).encode(),
            content_type="application/json",
        )

        # Invalidate cache
        self._local_cache = None
        await self.kv.delete(self._index_key())

    async def delete_connector(self, name: str) -> None:
        """Delete a connector configuration.

        Args:
            name: Connector name
        """
        key = f"{self._connectors_prefix()}{name}.json"
        await self.files.delete(key)

        # Invalidate cache
        self._local_cache = None
        await self.kv.delete(self._index_key())

    async def get_oauth_config(self, name: str) -> OAuthConfig | None:
        """Get OAuth configuration for a connector.

        Args:
            name: Connector name

        Returns:
            OAuth configuration or None
        """
        config = await self.get_connector(name)
        if not config or not config.oauth_config:
            return None

        oauth = config.oauth_config
        return OAuthConfig(
            client_id=oauth["client_id"],
            client_secret=oauth.get("client_secret"),
            authorization_url=oauth["authorization_url"],
            token_url=oauth["token_url"],
            scopes=oauth.get("scopes", []),
            use_pkce=oauth.get("use_pkce", True),
        )

    async def start_oauth_flow(
        self,
        name: str,
        redirect_uri: str,
        user_id: str,
        extra_scopes: list[str] | None = None,
    ) -> tuple[str, str]:
        """Start OAuth flow for a connector.

        Args:
            name: Connector name
            redirect_uri: OAuth callback URL
            user_id: User initiating the flow
            extra_scopes: Additional scopes to request

        Returns:
            Tuple of (authorization_url, state)

        Raises:
            ValueError: If connector not found or not OAuth
        """
        oauth_config = await self.get_oauth_config(name)
        if not oauth_config:
            raise ValueError(f"Connector '{name}' not found or not OAuth-enabled")

        return await self.oauth_manager.create_authorization_request(
            config=oauth_config,
            redirect_uri=redirect_uri,
            connector_name=name,
            user_id=user_id,
            extra_scopes=extra_scopes,
        )

    async def complete_oauth_flow(
        self,
        code: str,
        state: str,
    ) -> ConnectorCredentials:
        """Complete OAuth flow after callback.

        Args:
            code: Authorization code
            state: State from callback

        Returns:
            Connector credentials

        Raises:
            ValueError: If state invalid or connector not found
        """
        # Get state to find connector name
        oauth_state = await self.oauth_manager.get_state(state)
        if not oauth_state:
            raise ValueError("Invalid or expired OAuth state")

        oauth_config = await self.get_oauth_config(oauth_state.connector_name)
        if not oauth_config:
            raise ValueError(
                f"Connector '{oauth_state.connector_name}' not found or not OAuth-enabled"
            )

        return await self.oauth_manager.exchange_code(
            config=oauth_config,
            code=code,
            state=state,
        )

    async def get_credentials(
        self,
        user_id: str,
        connector_name: str,
        auto_refresh: bool = True,
    ) -> ConnectorCredentials | None:
        """Get credentials for a connector, refreshing if needed.

        Args:
            user_id: User ID
            connector_name: Connector name
            auto_refresh: Automatically refresh expired tokens

        Returns:
            Credentials or None
        """
        credentials = await self.oauth_manager.get_credentials(user_id, connector_name)
        if not credentials:
            return None

        # Check if token is expired and refresh if needed
        if auto_refresh and self.oauth_manager.is_token_expired(credentials):
            oauth_config = await self.get_oauth_config(connector_name)
            if oauth_config and credentials.refresh_token:
                try:
                    credentials = await self.oauth_manager.refresh_token(
                        oauth_config, credentials
                    )
                except Exception:
                    # Refresh failed, return existing credentials
                    pass

        return credentials

    async def revoke_credentials(
        self,
        user_id: str,
        connector_name: str,
    ) -> None:
        """Revoke/delete credentials for a connector.

        Args:
            user_id: User ID
            connector_name: Connector name
        """
        await self.oauth_manager.delete_credentials(user_id, connector_name)

    async def is_connected(
        self,
        user_id: str,
        connector_name: str,
    ) -> bool:
        """Check if user has valid credentials for a connector.

        Args:
            user_id: User ID
            connector_name: Connector name

        Returns:
            True if connected
        """
        credentials = await self.get_credentials(
            user_id, connector_name, auto_refresh=False
        )
        if not credentials:
            return False

        # Check if token is valid (not expired or has refresh capability)
        if self.oauth_manager.is_token_expired(credentials):
            return bool(credentials.refresh_token)

        return True
