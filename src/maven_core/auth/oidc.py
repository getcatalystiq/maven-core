"""OIDC (OpenID Connect) authentication."""

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from maven_core.exceptions import TokenExpiredError, TokenInvalidError


@dataclass
class OIDCTokenPayload:
    """Decoded OIDC token payload."""

    user_id: str  # 'sub' claim
    email: str | None
    email_verified: bool
    name: str | None
    issuer: str
    audience: str | list[str]
    issued_at: int
    expires_at: int
    raw: dict[str, Any]


class OIDCValidator:
    """Validates OIDC tokens from external identity providers."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_uri: str | None = None,
        cache_ttl: int = 3600,
    ) -> None:
        """Initialize OIDC validator.

        Args:
            issuer: Expected token issuer (e.g., "https://auth.example.com")
            audience: Expected audience (your app's client ID)
            jwks_uri: JWKS endpoint URL. If not provided, derived from issuer.
            cache_ttl: How long to cache JWKS keys in seconds
        """
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.jwks_uri = jwks_uri or f"{self.issuer}/.well-known/jwks.json"
        self.cache_ttl = cache_ttl

        # PyJWKClient handles caching internally
        self._jwks_client = PyJWKClient(self.jwks_uri, cache_keys=True)
        self._last_refresh = 0.0

    async def validate_token(self, token: str) -> OIDCTokenPayload:
        """Validate an OIDC token.

        Args:
            token: The encoded JWT token

        Returns:
            Decoded token payload

        Raises:
            TokenExpiredError: If the token has expired
            TokenInvalidError: If the token is invalid
        """
        try:
            # Get the signing key from JWKS
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)

            # Decode and validate
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self.audience,
                issuer=self.issuer,
                options={
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError("Token has expired") from e
        except jwt.InvalidTokenError as e:
            raise TokenInvalidError(f"Invalid OIDC token: {e}") from e
        except Exception as e:
            raise TokenInvalidError(f"Failed to validate OIDC token: {e}") from e

        return OIDCTokenPayload(
            user_id=payload.get("sub", ""),
            email=payload.get("email"),
            email_verified=payload.get("email_verified", False),
            name=payload.get("name"),
            issuer=payload.get("iss", ""),
            audience=payload.get("aud", ""),
            issued_at=payload.get("iat", 0),
            expires_at=payload.get("exp", 0),
            raw=payload,
        )

    async def refresh_keys(self) -> None:
        """Manually refresh the JWKS cache.

        This is called automatically when a key is not found,
        but can be called proactively.
        """
        # PyJWKClient doesn't have a public refresh method,
        # so we create a new client
        self._jwks_client = PyJWKClient(self.jwks_uri, cache_keys=True)
        self._last_refresh = time.time()


class OIDCDiscovery:
    """OIDC Discovery client for fetching provider configuration."""

    @staticmethod
    async def discover(issuer: str) -> dict[str, Any]:
        """Fetch OIDC provider configuration.

        Args:
            issuer: The issuer URL (e.g., "https://auth.example.com")

        Returns:
            OpenID Connect Discovery document

        Raises:
            TokenInvalidError: If discovery fails
        """
        discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(discovery_url, timeout=10.0)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                raise TokenInvalidError(f"OIDC discovery failed: {e}") from e
