"""Connector protocol for external service integrations."""

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ConnectorConfig:
    """Configuration for a connector."""

    name: str
    description: str
    connector_type: str  # "oauth", "api_key", "basic"
    base_url: str | None = None
    oauth_config: dict[str, Any] | None = None
    api_key_header: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorCredentials:
    """Credentials for a connector."""

    connector_name: str
    user_id: str
    credential_type: str  # "oauth_token", "api_key", "basic"
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: float | None = None
    api_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Connector(Protocol):
    """Protocol for external service connectors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Get connector name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Get connector description."""
        ...

    @abstractmethod
    async def is_configured(self) -> bool:
        """Check if connector is configured."""
        ...

    @abstractmethod
    async def get_tools(self) -> list[dict[str, Any]]:
        """Get available tools from this connector.

        Returns:
            List of tool definitions in MCP format
        """
        ...

    @abstractmethod
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credentials: ConnectorCredentials | None = None,
    ) -> Any:
        """Call a tool on this connector.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            credentials: User credentials for the connector

        Returns:
            Tool result
        """
        ...


@runtime_checkable
class OAuthConnector(Connector, Protocol):
    """Protocol for OAuth-based connectors."""

    @abstractmethod
    def get_authorization_url(
        self,
        state: str,
        redirect_uri: str,
        scopes: list[str] | None = None,
    ) -> str:
        """Get OAuth authorization URL.

        Args:
            state: CSRF protection state
            redirect_uri: Callback URL
            scopes: Requested scopes

        Returns:
            Authorization URL to redirect user to
        """
        ...

    @abstractmethod
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> ConnectorCredentials:
        """Exchange authorization code for tokens.

        Args:
            code: Authorization code from callback
            redirect_uri: Callback URL (must match authorization request)
            code_verifier: PKCE code verifier (if used)

        Returns:
            Connector credentials with tokens
        """
        ...

    @abstractmethod
    async def refresh_token(
        self,
        credentials: ConnectorCredentials,
    ) -> ConnectorCredentials:
        """Refresh expired access token.

        Args:
            credentials: Current credentials with refresh token

        Returns:
            Updated credentials with new access token
        """
        ...
