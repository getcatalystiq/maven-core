"""Maven Core exceptions."""


class MavenError(Exception):
    """Base exception for maven-core."""

    pass


class ConfigError(MavenError):
    """Configuration error."""

    pass


class AuthError(MavenError):
    """Authentication error."""

    pass


class InvalidCredentialsError(AuthError):
    """Invalid username or password."""

    pass


class TokenExpiredError(AuthError):
    """Token has expired."""

    pass


class TokenInvalidError(AuthError):
    """Token is invalid or malformed."""

    pass


class PermissionDeniedError(MavenError):
    """Permission denied for the requested operation."""

    pass


class NotFoundError(MavenError):
    """Resource not found."""

    pass


class SkillNotFoundError(NotFoundError):
    """Skill not found."""

    pass


class SessionNotFoundError(NotFoundError):
    """Session not found."""

    pass


class ConnectorError(MavenError):
    """Connector-related error."""

    pass


class OAuthError(ConnectorError):
    """OAuth flow error."""

    pass


class TokenRefreshError(ConnectorError):
    """Failed to refresh OAuth token."""

    pass


class SandboxError(MavenError):
    """Sandbox execution error."""

    pass


class SandboxTimeoutError(SandboxError):
    """Sandbox execution timed out."""

    pass


class TenantError(MavenError):
    """Tenant-related error."""

    pass


class TenantNotFoundError(TenantError):
    """Tenant not found."""

    pass


class TenantProvisioningError(TenantError):
    """Failed to provision tenant resources."""

    pass
