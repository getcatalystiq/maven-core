"""Authentication module."""

from maven_core.auth.jwt_utils import (
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from maven_core.auth.manager import AuthManager, AuthTokens, User
from maven_core.auth.oidc import OIDCTokenPayload, OIDCValidator
from maven_core.auth.password import hash_password, needs_rehash, verify_password

__all__ = [
    "AuthManager",
    "AuthTokens",
    "OIDCTokenPayload",
    "OIDCValidator",
    "TokenPayload",
    "User",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "needs_rehash",
    "verify_password",
]
