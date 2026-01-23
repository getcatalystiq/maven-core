"""Input validation utilities."""

import re

# Safe identifier pattern: alphanumeric, underscores, hyphens
# Must start with letter or number
SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

# Email pattern (simplified, RFC 5322 compliant for most cases)
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def validate_identifier(value: str, name: str = "identifier", max_length: int = 64) -> str:
    """Validate a safe identifier (tenant_id, user_id, session_id, etc).

    Args:
        value: The identifier to validate
        name: Name of the field for error messages
        max_length: Maximum allowed length

    Returns:
        The validated identifier

    Raises:
        ValueError: If the identifier is invalid
    """
    if not value:
        raise ValueError(f"{name} cannot be empty")

    if len(value) > max_length:
        raise ValueError(f"{name} exceeds maximum length of {max_length}")

    if not SAFE_IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid {name}: must start with alphanumeric and contain only "
            "alphanumeric characters, underscores, and hyphens"
        )

    # Prevent path traversal
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"Invalid {name}: contains forbidden characters")

    return value


def validate_email(email: str) -> str:
    """Validate an email address.

    Args:
        email: The email to validate

    Returns:
        The normalized (lowercased) email

    Raises:
        ValueError: If the email is invalid
    """
    if not email:
        raise ValueError("Email cannot be empty")

    email = email.strip().lower()

    if len(email) > 254:
        raise ValueError("Email exceeds maximum length")

    if not EMAIL_RE.match(email):
        raise ValueError("Invalid email format")

    return email


def validate_password(
    password: str,
    min_length: int = 12,
    require_special: bool = True,
) -> str:
    """Validate a password meets security requirements.

    Args:
        password: The password to validate
        min_length: Minimum required length
        require_special: Whether to require special characters

    Returns:
        The password (unchanged)

    Raises:
        ValueError: If the password doesn't meet requirements
    """
    if not password:
        raise ValueError("Password cannot be empty")

    if len(password) < min_length:
        raise ValueError(f"Password must be at least {min_length} characters")

    if require_special:
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            raise ValueError("Password must contain at least one special character")

    return password
