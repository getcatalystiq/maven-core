"""Tests for connector loader."""

import pytest
import time

from maven_core.backends.files.local import LocalFileStore
from maven_core.backends.kv.memory import MemoryKVStore
from maven_core.connectors.loader import ConnectorLoader
from maven_core.protocols.connector import ConnectorConfig, ConnectorCredentials


@pytest.fixture
def file_store(tmp_path) -> LocalFileStore:
    """Create a local file store."""
    return LocalFileStore(tmp_path)


@pytest.fixture
def kv_store() -> MemoryKVStore:
    """Create a memory KV store."""
    return MemoryKVStore()


@pytest.fixture
def loader(file_store, kv_store) -> ConnectorLoader:
    """Create a connector loader."""
    # Use a fixed Fernet key for testing
    test_key = "x7yMr-3qzKLNT9WvIjK6VxNm4KmJQxhPr5y8kQUhF3k="
    return ConnectorLoader(file_store, kv_store, "test-tenant", encryption_key=test_key)


class TestConnectorManagement:
    """Tests for connector configuration management."""

    @pytest.mark.asyncio
    async def test_save_and_get_connector(self, loader: ConnectorLoader) -> None:
        """Save and retrieve a connector."""
        config = ConnectorConfig(
            name="slack",
            description="Slack integration",
            connector_type="oauth",
            base_url="https://slack.com/api",
            oauth_config={
                "client_id": "test-client",
                "client_secret": "test-secret",
                "authorization_url": "https://slack.com/oauth/authorize",
                "token_url": "https://slack.com/api/oauth.access",
                "scopes": ["channels:read", "chat:write"],
            },
        )

        await loader.save_connector(config)
        retrieved = await loader.get_connector("slack")

        assert retrieved is not None
        assert retrieved.name == "slack"
        assert retrieved.description == "Slack integration"
        assert retrieved.connector_type == "oauth"
        assert retrieved.oauth_config is not None
        assert retrieved.oauth_config["client_id"] == "test-client"

    @pytest.mark.asyncio
    async def test_get_connector_not_found(self, loader: ConnectorLoader) -> None:
        """Non-existent connector returns None."""
        result = await loader.get_connector("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_connectors_empty(self, loader: ConnectorLoader) -> None:
        """List connectors when none exist."""
        connectors = await loader.list_connectors()
        assert connectors == []

    @pytest.mark.asyncio
    async def test_list_connectors(self, loader: ConnectorLoader) -> None:
        """List all connectors."""
        config1 = ConnectorConfig(
            name="slack",
            description="Slack",
            connector_type="oauth",
        )
        config2 = ConnectorConfig(
            name="github",
            description="GitHub",
            connector_type="oauth",
        )

        await loader.save_connector(config1)
        await loader.save_connector(config2)

        connectors = await loader.list_connectors()
        names = {c.name for c in connectors}

        assert len(connectors) == 2
        assert names == {"slack", "github"}

    @pytest.mark.asyncio
    async def test_delete_connector(self, loader: ConnectorLoader) -> None:
        """Delete a connector."""
        config = ConnectorConfig(
            name="to-delete",
            description="Will be deleted",
            connector_type="api_key",
        )

        await loader.save_connector(config)
        assert await loader.get_connector("to-delete") is not None

        await loader.delete_connector("to-delete")
        assert await loader.get_connector("to-delete") is None


class TestOAuthConfig:
    """Tests for OAuth configuration."""

    @pytest.mark.asyncio
    async def test_get_oauth_config(self, loader: ConnectorLoader) -> None:
        """Get OAuth config from connector."""
        config = ConnectorConfig(
            name="oauth-connector",
            description="OAuth test",
            connector_type="oauth",
            oauth_config={
                "client_id": "my-client",
                "client_secret": "my-secret",
                "authorization_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
                "scopes": ["read", "write"],
                "use_pkce": True,
            },
        )

        await loader.save_connector(config)
        oauth = await loader.get_oauth_config("oauth-connector")

        assert oauth is not None
        assert oauth.client_id == "my-client"
        assert oauth.client_secret == "my-secret"
        assert oauth.scopes == ["read", "write"]
        assert oauth.use_pkce is True

    @pytest.mark.asyncio
    async def test_get_oauth_config_not_oauth(self, loader: ConnectorLoader) -> None:
        """Non-OAuth connector returns None for OAuth config."""
        config = ConnectorConfig(
            name="api-key-connector",
            description="API key auth",
            connector_type="api_key",
            api_key_header="X-API-Key",
        )

        await loader.save_connector(config)
        oauth = await loader.get_oauth_config("api-key-connector")

        assert oauth is None

    @pytest.mark.asyncio
    async def test_get_oauth_config_not_found(self, loader: ConnectorLoader) -> None:
        """Non-existent connector returns None."""
        oauth = await loader.get_oauth_config("nonexistent")
        assert oauth is None


class TestOAuthFlow:
    """Tests for OAuth flow methods."""

    @pytest.mark.asyncio
    async def test_start_oauth_flow(self, loader: ConnectorLoader) -> None:
        """Start OAuth flow."""
        config = ConnectorConfig(
            name="oauth-test",
            description="OAuth test",
            connector_type="oauth",
            oauth_config={
                "client_id": "client-123",
                "client_secret": "secret-456",
                "authorization_url": "https://auth.example.com/authorize",
                "token_url": "https://auth.example.com/token",
                "scopes": ["read"],
            },
        )

        await loader.save_connector(config)

        auth_url, state = await loader.start_oauth_flow(
            name="oauth-test",
            redirect_uri="https://app.example.com/callback",
            user_id="user-1",
        )

        assert "client_id=client-123" in auth_url
        assert len(state) > 10  # State should be a reasonable length

    @pytest.mark.asyncio
    async def test_start_oauth_flow_not_found(self, loader: ConnectorLoader) -> None:
        """Start OAuth flow for non-existent connector raises error."""
        with pytest.raises(ValueError, match="not found"):
            await loader.start_oauth_flow(
                name="nonexistent",
                redirect_uri="https://app.example.com/callback",
                user_id="user-1",
            )

    @pytest.mark.asyncio
    async def test_start_oauth_flow_not_oauth(self, loader: ConnectorLoader) -> None:
        """Start OAuth flow for non-OAuth connector raises error."""
        config = ConnectorConfig(
            name="api-key",
            description="API key auth",
            connector_type="api_key",
        )
        await loader.save_connector(config)

        with pytest.raises(ValueError, match="not OAuth-enabled"):
            await loader.start_oauth_flow(
                name="api-key",
                redirect_uri="https://app.example.com/callback",
                user_id="user-1",
            )


class TestCredentialManagement:
    """Tests for credential management through loader."""

    @pytest.mark.asyncio
    async def test_get_credentials(self, loader: ConnectorLoader) -> None:
        """Get stored credentials."""
        # Store credentials directly via OAuth manager
        credentials = ConnectorCredentials(
            connector_name="test-connector",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=time.time() + 3600,
        )
        await loader.oauth_manager.store_credentials(credentials)

        retrieved = await loader.get_credentials("user-1", "test-connector")

        assert retrieved is not None
        assert retrieved.access_token == "access-token"

    @pytest.mark.asyncio
    async def test_get_credentials_not_found(self, loader: ConnectorLoader) -> None:
        """Get non-existent credentials returns None."""
        result = await loader.get_credentials("user-1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_revoke_credentials(self, loader: ConnectorLoader) -> None:
        """Revoke credentials."""
        credentials = ConnectorCredentials(
            connector_name="test-connector",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access-token",
        )
        await loader.oauth_manager.store_credentials(credentials)

        await loader.revoke_credentials("user-1", "test-connector")

        result = await loader.get_credentials("user-1", "test-connector")
        assert result is None

    @pytest.mark.asyncio
    async def test_is_connected_true(self, loader: ConnectorLoader) -> None:
        """Check connected status when credentials exist."""
        credentials = ConnectorCredentials(
            connector_name="test-connector",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access-token",
            expires_at=time.time() + 3600,
        )
        await loader.oauth_manager.store_credentials(credentials)

        assert await loader.is_connected("user-1", "test-connector") is True

    @pytest.mark.asyncio
    async def test_is_connected_false_no_creds(self, loader: ConnectorLoader) -> None:
        """Not connected when no credentials."""
        assert await loader.is_connected("user-1", "nonexistent") is False

    @pytest.mark.asyncio
    async def test_is_connected_expired_with_refresh(
        self,
        loader: ConnectorLoader,
    ) -> None:
        """Connected if token expired but has refresh token."""
        credentials = ConnectorCredentials(
            connector_name="test-connector",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="expired-access",
            refresh_token="valid-refresh",
            expires_at=time.time() - 100,  # Expired
        )
        await loader.oauth_manager.store_credentials(credentials)

        assert await loader.is_connected("user-1", "test-connector") is True

    @pytest.mark.asyncio
    async def test_is_connected_expired_no_refresh(
        self,
        loader: ConnectorLoader,
    ) -> None:
        """Not connected if token expired and no refresh token."""
        credentials = ConnectorCredentials(
            connector_name="test-connector",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="expired-access",
            refresh_token=None,
            expires_at=time.time() - 100,  # Expired
        )
        await loader.oauth_manager.store_credentials(credentials)

        assert await loader.is_connected("user-1", "test-connector") is False


class TestIndexCaching:
    """Tests for connector index caching."""

    @pytest.mark.asyncio
    async def test_index_is_cached(self, loader: ConnectorLoader) -> None:
        """Index is cached locally."""
        config = ConnectorConfig(
            name="cached-connector",
            description="For cache test",
            connector_type="oauth",
        )
        await loader.save_connector(config)

        # First call builds index
        await loader.list_connectors()
        assert loader._local_cache is not None
        first_built = loader._local_cache.built_at

        # Second call uses cache
        await loader.list_connectors()
        assert loader._local_cache.built_at == first_built

    @pytest.mark.asyncio
    async def test_save_invalidates_cache(self, loader: ConnectorLoader) -> None:
        """Saving a connector invalidates cache."""
        config1 = ConnectorConfig(
            name="first",
            description="First",
            connector_type="oauth",
        )
        await loader.save_connector(config1)
        await loader.list_connectors()

        assert loader._local_cache is not None

        # Save another connector
        config2 = ConnectorConfig(
            name="second",
            description="Second",
            connector_type="oauth",
        )
        await loader.save_connector(config2)

        # Cache should be invalidated
        assert loader._local_cache is None
