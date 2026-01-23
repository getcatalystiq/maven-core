"""Password authentication with argon2id hashing."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from maven_core.exceptions import InvalidCredentialsError

# Argon2id parameters (OWASP recommendations)
_hasher = PasswordHasher(
    time_cost=3,        # iterations
    memory_cost=65536,  # 64 MB
    parallelism=4,      # threads
    hash_len=32,        # output length
)


def hash_password(password: str) -> str:
    """Hash a password using argon2id.

    Args:
        password: The plaintext password

    Returns:
        The hashed password (includes salt and parameters)
    """
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a hash.

    Args:
        password: The plaintext password to verify
        password_hash: The stored password hash

    Returns:
        True if the password matches

    Raises:
        InvalidCredentialsError: If the password doesn't match
    """
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError) as e:
        raise InvalidCredentialsError("Invalid password") from e


def needs_rehash(password_hash: str) -> bool:
    """Check if a password hash needs to be rehashed.

    This is useful when upgrading hashing parameters.

    Args:
        password_hash: The stored password hash

    Returns:
        True if the hash should be rehashed with current parameters
    """
    return _hasher.check_needs_rehash(password_hash)
