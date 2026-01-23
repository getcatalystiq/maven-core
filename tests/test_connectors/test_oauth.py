"""Tests for OAuth manager."""

import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock

from maven_core.backends.kv.memory import MemoryKVStore
from maven_core.connectors.oauth import OAuthConfig, OAuthManager, OAuthState
from maven_core.protocols.connector import ConnectorCredentials


@pytest.fixture
def kv_store() -> MemoryKVStore:
    """Create a memory KV store."""
    return MemoryKVStore()


@pytest.fixture
def oauth_manager(kv_store) -> OAuthManager:
    """Create an OAuth manager."""
    return OAuthManager(kv_store, "test-tenant")


@pytest.fixture
def oauth_config() -> OAuthConfig:
    """Create a sample OAuth config."""
    return OAuthConfig(
        client_id="test-client-id",
        client_secret="test-client-secret",
        authorization_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        scopes=["read", "write"],
        use_pkce=True,
    )


class TestPKCE:
    """Tests for PKCE generation."""

    def test_generate_pkce(self) -> None:
        """Generate PKCE code verifier and challenge."""
        verifier, challenge = OAuthManager.generate_pkce()

        # Verifier should be URL-safe base64
        assert len(verifier) > 32
        assert all(c.isalnum() or c in "-_" for c in verifier)

        # Challenge should be different from verifier
        assert challenge != verifier

        # Challenge should be URL-safe base64
        assert all(c.isalnum() or c in "-_" for c in challenge)

    def test_generate_pkce_unique(self) -> None:
        """Each PKCE generation should be unique."""
        pairs = [OAuthManager.generate_pkce() for _ in range(10)]
        verifiers = [v for v, c in pairs]
        challenges = [c for v, c in pairs]

        assert len(set(verifiers)) == 10
        assert len(set(challenges)) == 10


class TestAuthorizationRequest:
    """Tests for OAuth authorization request."""

    @pytest.mark.asyncio
    async def test_create_authorization_request(
        self,
        oauth_manager: OAuthManager,
        oauth_config: OAuthConfig,
    ) -> None:
        """Create authorization request."""
        auth_url, state = await oauth_manager.create_authorization_request(
            config=oauth_config,
            redirect_uri="https://app.example.com/callback",
            connector_name="test-connector",
            user_id="user-1",
        )

        # URL should contain required parameters
        assert "client_id=test-client-id" in auth_url
        assert "redirect_uri=" in auth_url
        assert "response_type=code" in auth_url
        assert f"state={state}" in auth_url
        assert "scope=" in auth_url

        # PKCE parameters
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url

        # State should be stored
        stored_state = await oauth_manager.get_state(state)
        assert stored_state is not None
        assert stored_state.connector_name == "test-connector"
        assert stored_state.user_id == "user-1"

    @pytest.mark.asyncio
    async def test_create_authorization_request_extra_scopes(
        self,
        oauth_manager: OAuthManager,
        oauth_config: OAuthConfig,
    ) -> None:
        """Extra scopes are included."""
        auth_url, _ = await oauth_manager.create_authorization_request(
            config=oauth_config,
            redirect_uri="https://app.example.com/callback",
            connector_name="test",
            user_id="user-1",
            extra_scopes=["extra1", "extra2"],
        )

        # All scopes should be in URL (URL-encoded spaces)
        assert "read" in auth_url
        assert "write" in auth_url
        assert "extra1" in auth_url
        assert "extra2" in auth_url

    @pytest.mark.asyncio
    async def test_create_authorization_request_no_pkce(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """PKCE can be disabled."""
        config = OAuthConfig(
            client_id="test",
            client_secret="secret",
            authorization_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            scopes=["read"],
            use_pkce=False,
        )

        auth_url, state = await oauth_manager.create_authorization_request(
            config=config,
            redirect_uri="https://app.example.com/callback",
            connector_name="test",
            user_id="user-1",
        )

        # PKCE parameters should not be present
        assert "code_challenge" not in auth_url

        # State should not have code verifier
        stored_state = await oauth_manager.get_state(state)
        assert stored_state.code_verifier is None


class TestStateManagement:
    """Tests for OAuth state management."""

    @pytest.mark.asyncio
    async def test_get_state(
        self,
        oauth_manager: OAuthManager,
        oauth_config: OAuthConfig,
    ) -> None:
        """Retrieve stored state."""
        _, state = await oauth_manager.create_authorization_request(
            config=oauth_config,
            redirect_uri="https://app.example.com/callback",
            connector_name="my-connector",
            user_id="user-123",
        )

        retrieved = await oauth_manager.get_state(state)

        assert retrieved is not None
        assert retrieved.state == state
        assert retrieved.connector_name == "my-connector"
        assert retrieved.user_id == "user-123"
        assert retrieved.redirect_uri == "https://app.example.com/callback"
        assert retrieved.code_verifier is not None  # PKCE enabled

    @pytest.mark.asyncio
    async def test_get_state_not_found(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """Non-existent state returns None."""
        result = await oauth_manager.get_state("nonexistent")
        assert result is None


class TestCredentialStorage:
    """Tests for credential storage."""

    @pytest.mark.asyncio
    async def test_store_and_get_credentials(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """Store and retrieve credentials."""
        credentials = ConnectorCredentials(
            connector_name="test-connector",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access-123",
            refresh_token="refresh-456",
            expires_at=time.time() + 3600,
            metadata={"scope": "read write"},
        )

        await oauth_manager.store_credentials(credentials)
        retrieved = await oauth_manager.get_credentials("user-1", "test-connector")

        assert retrieved is not None
        assert retrieved.access_token == "access-123"
        assert retrieved.refresh_token == "refresh-456"
        assert retrieved.metadata["scope"] == "read write"

    @pytest.mark.asyncio
    async def test_get_credentials_not_found(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """Non-existent credentials returns None."""
        result = await oauth_manager.get_credentials("user-1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_credentials(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """Delete stored credentials."""
        credentials = ConnectorCredentials(
            connector_name="test-connector",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access-123",
        )

        await oauth_manager.store_credentials(credentials)

        # Verify exists
        assert await oauth_manager.get_credentials("user-1", "test-connector") is not None

        # Delete
        await oauth_manager.delete_credentials("user-1", "test-connector")

        # Verify gone
        assert await oauth_manager.get_credentials("user-1", "test-connector") is None


class TestTokenExpiry:
    """Tests for token expiry checking."""

    def test_is_token_expired_no_expiry(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """Token without expiry is not expired."""
        credentials = ConnectorCredentials(
            connector_name="test",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access",
            expires_at=None,
        )

        assert oauth_manager.is_token_expired(credentials) is False

    def test_is_token_expired_future(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """Token expiring in the future is not expired."""
        credentials = ConnectorCredentials(
            connector_name="test",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access",
            expires_at=time.time() + 3600,  # 1 hour from now
        )

        assert oauth_manager.is_token_expired(credentials) is False

    def test_is_token_expired_past(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """Token that expired is expired."""
        credentials = ConnectorCredentials(
            connector_name="test",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access",
            expires_at=time.time() - 100,  # 100 seconds ago
        )

        assert oauth_manager.is_token_expired(credentials) is True

    def test_is_token_expired_buffer(
        self,
        oauth_manager: OAuthManager,
    ) -> None:
        """Token expiring within buffer is considered expired."""
        credentials = ConnectorCredentials(
            connector_name="test",
            user_id="user-1",
            credential_type="oauth_token",
            access_token="access",
            expires_at=time.time() + 30,  # 30 seconds from now
        )

        # Default buffer is 60 seconds
        assert oauth_manager.is_token_expired(credentials) is True

        # With smaller buffer, not expired
        assert oauth_manager.is_token_expired(credentials, buffer_seconds=10) is False
