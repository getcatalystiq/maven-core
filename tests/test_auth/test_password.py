"""Tests for password hashing."""

import pytest

from maven_core.auth.password import hash_password, needs_rehash, verify_password
from maven_core.exceptions import InvalidCredentialsError


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password(self):
        """Test that password hashing produces a hash."""
        password = "SecureP@ssword123!"
        hashed = hash_password(password)

        assert hashed != password
        assert hashed.startswith("$argon2id$")

    def test_verify_password_correct(self):
        """Test that correct password verification passes."""
        password = "SecureP@ssword123!"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test that incorrect password raises InvalidCredentialsError."""
        password = "SecureP@ssword123!"
        hashed = hash_password(password)

        with pytest.raises(InvalidCredentialsError):
            verify_password("WrongPassword!", hashed)

    def test_different_passwords_different_hashes(self):
        """Test that different passwords produce different hashes."""
        hash1 = hash_password("Password1!")
        hash2 = hash_password("Password2!")

        assert hash1 != hash2

    def test_same_password_different_hashes(self):
        """Test that same password produces different hashes (due to salt)."""
        password = "SecureP@ssword123!"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Hashes should be different due to random salt
        assert hash1 != hash2

        # But both should verify correctly
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True

    def test_needs_rehash_fresh_hash(self):
        """Test that fresh hash doesn't need rehash."""
        password = "SecureP@ssword123!"
        hashed = hash_password(password)

        assert needs_rehash(hashed) is False
