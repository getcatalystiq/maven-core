"""JWT token utilities."""

import time
from dataclasses import dataclass
from typing import Any

import jwt

from maven_core.exceptions import TokenExpiredError, TokenInvalidError


@dataclass
class TokenPayload:
    """Decoded JWT token payload."""

    user_id: str
    tenant_id: str
    email: str | None
    roles: list[str]
    issued_at: int
    expires_at: int
    token_type: str  # "access" or "refresh"
    raw: dict[str, Any]  # Full payload for custom claims


def create_access_token(
    user_id: str,
    tenant_id: str,
    secret: str,
    expiry_minutes: int = 15,
    email: str | None = None,
    roles: list[str] | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create an access token.

    Args:
        user_id: The user ID
        tenant_id: The tenant ID
        secret: JWT signing secret
        expiry_minutes: Token expiry in minutes
        email: Optional user email
        roles: Optional list of roles
        extra_claims: Optional extra claims to include

    Returns:
        Encoded JWT token
    """
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "iat": now,
        "exp": now + (expiry_minutes * 60),
        "type": "access",
    }

    if email:
        payload["email"] = email
    if roles:
        payload["roles"] = roles
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, secret, algorithm="HS256")


def create_refresh_token(
    user_id: str,
    tenant_id: str,
    secret: str,
    expiry_days: int = 30,
) -> str:
    """Create a refresh token.

    Args:
        user_id: The user ID
        tenant_id: The tenant ID
        secret: JWT signing secret
        expiry_days: Token expiry in days

    Returns:
        Encoded JWT refresh token
    """
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "iat": now,
        "exp": now + (expiry_days * 24 * 60 * 60),
        "type": "refresh",
    }

    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str, verify_exp: bool = True) -> TokenPayload:
    """Decode and validate a JWT token.

    Args:
        token: The encoded JWT token
        secret: JWT signing secret
        verify_exp: Whether to verify expiration

    Returns:
        Decoded token payload

    Raises:
        TokenExpiredError: If the token has expired
        TokenInvalidError: If the token is invalid
    """
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_exp": verify_exp},
        )
    except jwt.ExpiredSignatureError as e:
        raise TokenExpiredError("Token has expired") from e
    except jwt.InvalidTokenError as e:
        raise TokenInvalidError(f"Invalid token: {e}") from e

    return TokenPayload(
        user_id=payload.get("sub", ""),
        tenant_id=payload.get("tid", ""),
        email=payload.get("email"),
        roles=payload.get("roles", []),
        issued_at=payload.get("iat", 0),
        expires_at=payload.get("exp", 0),
        token_type=payload.get("type", "access"),
        raw=payload,
    )
