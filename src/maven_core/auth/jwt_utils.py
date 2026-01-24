"""JWT token utilities with RS256 asymmetric signing."""

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

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


@dataclass
class JWTKeyPair:
    """RSA key pair for JWT signing."""

    private_key: bytes  # PEM-encoded private key
    public_key: bytes  # PEM-encoded public key
    key_id: str  # Key ID for JWKS


def generate_key_pair(key_id: str = "maven-core-1") -> JWTKeyPair:
    """Generate a new RSA key pair for JWT signing.

    Args:
        key_id: Key identifier for JWKS

    Returns:
        JWTKeyPair with private and public keys
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return JWTKeyPair(
        private_key=private_pem,
        public_key=public_pem,
        key_id=key_id,
    )


def load_key_pair(
    private_key_path: str | Path | None = None,
    public_key_path: str | Path | None = None,
    key_id: str = "maven-core-1",
) -> JWTKeyPair:
    """Load or generate RSA key pair.

    If paths are provided, loads existing keys. Otherwise generates new ones.

    Args:
        private_key_path: Path to PEM private key file
        public_key_path: Path to PEM public key file
        key_id: Key identifier for JWKS

    Returns:
        JWTKeyPair with loaded or generated keys
    """
    if private_key_path and public_key_path:
        private_path = Path(private_key_path)
        public_path = Path(public_key_path)

        if private_path.exists() and public_path.exists():
            return JWTKeyPair(
                private_key=private_path.read_bytes(),
                public_key=public_path.read_bytes(),
                key_id=key_id,
            )

    # Generate new key pair
    key_pair = generate_key_pair(key_id)

    # Save if paths provided
    if private_key_path and public_key_path:
        private_path = Path(private_key_path)
        public_path = Path(public_key_path)
        private_path.parent.mkdir(parents=True, exist_ok=True)
        public_path.parent.mkdir(parents=True, exist_ok=True)
        private_path.write_bytes(key_pair.private_key)
        public_path.write_bytes(key_pair.public_key)
        # Secure the private key
        private_path.chmod(0o600)

    return key_pair


def create_jwks(key_pair: JWTKeyPair) -> dict[str, Any]:
    """Create JWKS (JSON Web Key Set) from public key.

    Args:
        key_pair: Key pair containing public key

    Returns:
        JWKS dictionary with public key
    """
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    public_key = load_pem_public_key(key_pair.public_key)
    public_numbers = public_key.public_numbers()  # type: ignore

    # Convert to base64url encoding (no padding)
    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    # Get n and e as bytes (big-endian, no leading zeros except for sign)
    n_bytes = public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
    e_bytes = public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": key_pair.key_id,
                "n": b64url(n_bytes),
                "e": b64url(e_bytes),
            }
        ]
    }


def create_access_token(
    user_id: str,
    tenant_id: str,
    private_key: bytes,
    key_id: str,
    issuer: str,
    expiry_minutes: int = 15,
    email: str | None = None,
    roles: list[str] | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create an access token using RS256.

    Args:
        user_id: The user ID
        tenant_id: The tenant ID
        private_key: PEM-encoded RSA private key
        key_id: Key ID for JWT header
        issuer: Token issuer (typically the API URL)
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
        "iss": issuer,
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

    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def create_refresh_token(
    user_id: str,
    tenant_id: str,
    private_key: bytes,
    key_id: str,
    issuer: str,
    expiry_days: int = 30,
) -> str:
    """Create a refresh token using RS256.

    Args:
        user_id: The user ID
        tenant_id: The tenant ID
        private_key: PEM-encoded RSA private key
        key_id: Key ID for JWT header
        issuer: Token issuer
        expiry_days: Token expiry in days

    Returns:
        Encoded JWT refresh token
    """
    now = int(time.time())
    payload = {
        "sub": user_id,
        "tid": tenant_id,
        "iss": issuer,
        "iat": now,
        "exp": now + (expiry_days * 24 * 60 * 60),
        "type": "refresh",
    }

    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def decode_token(
    token: str,
    public_key: bytes,
    issuer: str | None = None,
    verify_exp: bool = True,
) -> TokenPayload:
    """Decode and validate a JWT token using RS256.

    Args:
        token: The encoded JWT token
        public_key: PEM-encoded RSA public key
        issuer: Expected issuer (optional)
        verify_exp: Whether to verify expiration

    Returns:
        Decoded token payload

    Raises:
        TokenExpiredError: If the token has expired
        TokenInvalidError: If the token is invalid
    """
    try:
        options = {"verify_exp": verify_exp}
        if issuer:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                options=options,
                issuer=issuer,
            )
        else:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                options=options,
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


def decode_token_with_jwks(
    token: str,
    jwks_client: "jwt.PyJWKClient",
    issuer: str | None = None,
    verify_exp: bool = True,
) -> TokenPayload:
    """Decode and validate a JWT token using JWKS.

    Args:
        token: The encoded JWT token
        jwks_client: PyJWKClient for fetching public keys
        issuer: Expected issuer (optional)
        verify_exp: Whether to verify expiration

    Returns:
        Decoded token payload

    Raises:
        TokenExpiredError: If the token has expired
        TokenInvalidError: If the token is invalid
    """
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        options = {"verify_exp": verify_exp}

        if issuer:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options=options,
                issuer=issuer,
            )
        else:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options=options,
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
