"""Cryptographic utilities."""

import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode

from cryptography.fernet import Fernet


def generate_secret_key() -> str:
    """Generate a new Fernet-compatible secret key.

    Returns:
        Base64-encoded 32-byte key suitable for Fernet encryption
    """
    return Fernet.generate_key().decode()


def generate_random_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token.

    Args:
        length: Number of bytes (output will be URL-safe base64, ~4/3 longer)

    Returns:
        URL-safe base64-encoded random string
    """
    return secrets.token_urlsafe(length)


class TokenEncryption:
    """Fernet-based token encryption for OAuth tokens.

    Uses symmetric encryption to protect tokens at rest.
    """

    def __init__(self, key: str | bytes) -> None:
        """Initialize token encryption.

        Args:
            key: Fernet-compatible key (32 bytes, URL-safe base64 encoded)
        """
        if isinstance(key, str):
            key = key.encode()
        self.fernet = Fernet(key)

    def encrypt(self, token: str) -> str:
        """Encrypt a token.

        Args:
            token: Plaintext token

        Returns:
            Encrypted token (URL-safe base64)
        """
        encrypted = self.fernet.encrypt(token.encode())
        return encrypted.decode()

    def decrypt(self, encrypted: str) -> str:
        """Decrypt a token.

        Args:
            encrypted: Encrypted token (URL-safe base64)

        Returns:
            Plaintext token
        """
        decrypted = self.fernet.decrypt(encrypted.encode())
        return decrypted.decode()
