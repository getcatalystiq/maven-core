"""OAuth token management with PKCE support."""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx

from maven_core.protocols import KVStore
from maven_core.protocols.connector import ConnectorCredentials


@dataclass
class OAuthConfig:
    """OAuth provider configuration."""

    client_id: str
    client_secret: str | None  # None for public clients (PKCE only)
    authorization_url: str
    token_url: str
    scopes: list[str]
    use_pkce: bool = True


@dataclass
class OAuthState:
    """OAuth state for CSRF protection and PKCE."""

    state: str
    code_verifier: str | None  # For PKCE
    redirect_uri: str
    connector_name: str
    user_id: str
    created_at: float


class OAuthManager:
    """Manages OAuth flows and token storage."""

    def __init__(
        self,
        kv: KVStore,
        tenant_id: str,
        state_ttl: int = 600,  # 10 minutes
    ) -> None:
        """Initialize OAuth manager.

        Args:
            kv: KV store for state and tokens
            tenant_id: Current tenant ID
            state_ttl: TTL for OAuth state (seconds)
        """
        self.kv = kv
        self.tenant_id = tenant_id
        self.state_ttl = state_ttl

    def _state_key(self, state: str) -> str:
        """Get KV key for OAuth state."""
        return f"oauth_state:{self.tenant_id}:{state}"

    def _token_key(self, user_id: str, connector_name: str) -> str:
        """Get KV key for stored tokens."""
        return f"oauth_token:{self.tenant_id}:{user_id}:{connector_name}"

    @staticmethod
    def generate_pkce() -> tuple[str, str]:
        """Generate PKCE code verifier and challenge.

        Returns:
            Tuple of (code_verifier, code_challenge)
        """
        # Generate random 43-128 character code verifier
        code_verifier = secrets.token_urlsafe(32)

        # Create code challenge using S256 method
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

        return code_verifier, code_challenge

    async def create_authorization_request(
        self,
        config: OAuthConfig,
        redirect_uri: str,
        connector_name: str,
        user_id: str,
        extra_scopes: list[str] | None = None,
    ) -> tuple[str, str]:
        """Create OAuth authorization request.

        Args:
            config: OAuth provider configuration
            redirect_uri: Callback URL
            connector_name: Name of the connector
            user_id: User initiating the flow
            extra_scopes: Additional scopes to request

        Returns:
            Tuple of (authorization_url, state)
        """
        import json
        from urllib.parse import urlencode

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        # Generate PKCE if enabled
        code_verifier = None
        code_challenge = None
        if config.use_pkce:
            code_verifier, code_challenge = self.generate_pkce()

        # Store state
        oauth_state = OAuthState(
            state=state,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            connector_name=connector_name,
            user_id=user_id,
            created_at=time.time(),
        )
        await self.kv.set(
            self._state_key(state),
            json.dumps({
                "state": oauth_state.state,
                "code_verifier": oauth_state.code_verifier,
                "redirect_uri": oauth_state.redirect_uri,
                "connector_name": oauth_state.connector_name,
                "user_id": oauth_state.user_id,
                "created_at": oauth_state.created_at,
            }).encode(),
            ttl=self.state_ttl,
        )

        # Build authorization URL
        scopes = config.scopes + (extra_scopes or [])
        params = {
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": " ".join(scopes),
        }

        if config.use_pkce:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        auth_url = f"{config.authorization_url}?{urlencode(params)}"
        return auth_url, state

    async def get_state(self, state: str) -> OAuthState | None:
        """Retrieve OAuth state.

        Args:
            state: State value from callback

        Returns:
            OAuth state or None if not found/expired
        """
        import json

        data = await self.kv.get(self._state_key(state))
        if not data:
            return None

        try:
            parsed = json.loads(data.decode())
            return OAuthState(
                state=parsed["state"],
                code_verifier=parsed.get("code_verifier"),
                redirect_uri=parsed["redirect_uri"],
                connector_name=parsed["connector_name"],
                user_id=parsed["user_id"],
                created_at=parsed["created_at"],
            )
        except (json.JSONDecodeError, KeyError):
            return None

    async def exchange_code(
        self,
        config: OAuthConfig,
        code: str,
        state: str,
    ) -> ConnectorCredentials:
        """Exchange authorization code for tokens.

        Args:
            config: OAuth provider configuration
            code: Authorization code from callback
            state: State value from callback

        Returns:
            Connector credentials with tokens

        Raises:
            ValueError: If state is invalid or expired
        """
        # Retrieve and validate state
        oauth_state = await self.get_state(state)
        if not oauth_state:
            raise ValueError("Invalid or expired OAuth state")

        # Build token request
        data: dict[str, Any] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": oauth_state.redirect_uri,
            "client_id": config.client_id,
        }

        if config.client_secret:
            data["client_secret"] = config.client_secret

        if oauth_state.code_verifier:
            data["code_verifier"] = oauth_state.code_verifier

        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            response = await client.post(
                config.token_url,
                data=data,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            tokens = response.json()

        # Calculate expiry time
        expires_at = None
        if "expires_in" in tokens:
            expires_at = time.time() + tokens["expires_in"]

        # Create credentials
        credentials = ConnectorCredentials(
            connector_name=oauth_state.connector_name,
            user_id=oauth_state.user_id,
            credential_type="oauth_token",
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            expires_at=expires_at,
            metadata={
                "scope": tokens.get("scope", ""),
                "token_type": tokens.get("token_type", "Bearer"),
            },
        )

        # Store credentials
        await self.store_credentials(credentials)

        # Clean up state
        await self.kv.delete(self._state_key(state))

        return credentials

    async def refresh_token(
        self,
        config: OAuthConfig,
        credentials: ConnectorCredentials,
    ) -> ConnectorCredentials:
        """Refresh expired access token.

        Args:
            config: OAuth provider configuration
            credentials: Current credentials with refresh token

        Returns:
            Updated credentials

        Raises:
            ValueError: If no refresh token available
        """
        if not credentials.refresh_token:
            raise ValueError("No refresh token available")

        # Build refresh request
        data: dict[str, Any] = {
            "grant_type": "refresh_token",
            "refresh_token": credentials.refresh_token,
            "client_id": config.client_id,
        }

        if config.client_secret:
            data["client_secret"] = config.client_secret

        # Refresh tokens
        async with httpx.AsyncClient() as client:
            response = await client.post(
                config.token_url,
                data=data,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            tokens = response.json()

        # Calculate expiry time
        expires_at = None
        if "expires_in" in tokens:
            expires_at = time.time() + tokens["expires_in"]

        # Update credentials
        updated = ConnectorCredentials(
            connector_name=credentials.connector_name,
            user_id=credentials.user_id,
            credential_type="oauth_token",
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", credentials.refresh_token),
            expires_at=expires_at,
            metadata={
                "scope": tokens.get("scope", credentials.metadata.get("scope", "")),
                "token_type": tokens.get(
                    "token_type",
                    credentials.metadata.get("token_type", "Bearer"),
                ),
            },
        )

        # Store updated credentials
        await self.store_credentials(updated)

        return updated

    async def store_credentials(self, credentials: ConnectorCredentials) -> None:
        """Store credentials in KV.

        Args:
            credentials: Credentials to store
        """
        import json

        key = self._token_key(credentials.user_id, credentials.connector_name)
        data = json.dumps({
            "connector_name": credentials.connector_name,
            "user_id": credentials.user_id,
            "credential_type": credentials.credential_type,
            "access_token": credentials.access_token,
            "refresh_token": credentials.refresh_token,
            "expires_at": credentials.expires_at,
            "api_key": credentials.api_key,
            "metadata": credentials.metadata,
        }).encode()

        await self.kv.set(key, data)

    async def get_credentials(
        self,
        user_id: str,
        connector_name: str,
    ) -> ConnectorCredentials | None:
        """Get stored credentials.

        Args:
            user_id: User ID
            connector_name: Connector name

        Returns:
            Stored credentials or None
        """
        import json

        key = self._token_key(user_id, connector_name)
        data = await self.kv.get(key)

        if not data:
            return None

        try:
            parsed = json.loads(data.decode())
            return ConnectorCredentials(
                connector_name=parsed["connector_name"],
                user_id=parsed["user_id"],
                credential_type=parsed["credential_type"],
                access_token=parsed.get("access_token"),
                refresh_token=parsed.get("refresh_token"),
                expires_at=parsed.get("expires_at"),
                api_key=parsed.get("api_key"),
                metadata=parsed.get("metadata", {}),
            )
        except (json.JSONDecodeError, KeyError):
            return None

    async def delete_credentials(
        self,
        user_id: str,
        connector_name: str,
    ) -> None:
        """Delete stored credentials.

        Args:
            user_id: User ID
            connector_name: Connector name
        """
        key = self._token_key(user_id, connector_name)
        await self.kv.delete(key)

    def is_token_expired(
        self,
        credentials: ConnectorCredentials,
        buffer_seconds: int = 60,
    ) -> bool:
        """Check if access token is expired or expiring soon.

        Args:
            credentials: Credentials to check
            buffer_seconds: Consider expired if within this many seconds

        Returns:
            True if token is expired or expiring soon
        """
        if credentials.expires_at is None:
            return False  # No expiry info, assume valid

        return time.time() + buffer_seconds >= credentials.expires_at
