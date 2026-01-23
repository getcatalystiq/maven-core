"""Tests for JWT utilities."""

import time

import pytest

from maven_core.auth.jwt_utils import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from maven_core.exceptions import TokenExpiredError, TokenInvalidError


class TestJWTUtils:
    """Tests for JWT utilities."""

    def test_create_and_decode_access_token(self):
        """Test creating and decoding an access token."""
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            secret="test-secret",
            expiry_minutes=15,
            email="test@example.com",
            roles=["user", "admin"],
        )

        payload = decode_token(token, "test-secret")

        assert payload.user_id == "user-123"
        assert payload.tenant_id == "tenant-456"
        assert payload.email == "test@example.com"
        assert payload.roles == ["user", "admin"]
        assert payload.token_type == "access"

    def test_create_and_decode_refresh_token(self):
        """Test creating and decoding a refresh token."""
        token = create_refresh_token(
            user_id="user-123",
            tenant_id="tenant-456",
            secret="test-secret",
            expiry_days=30,
        )

        payload = decode_token(token, "test-secret")

        assert payload.user_id == "user-123"
        assert payload.tenant_id == "tenant-456"
        assert payload.token_type == "refresh"

    def test_decode_with_wrong_secret(self):
        """Test that decoding with wrong secret fails."""
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            secret="correct-secret",
        )

        with pytest.raises(TokenInvalidError):
            decode_token(token, "wrong-secret")

    def test_expired_token(self):
        """Test that expired token raises TokenExpiredError."""
        # Create a token that's already expired
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            secret="test-secret",
            expiry_minutes=-1,  # Already expired
        )

        with pytest.raises(TokenExpiredError):
            decode_token(token, "test-secret")

    def test_decode_without_exp_verification(self):
        """Test decoding expired token without verification."""
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            secret="test-secret",
            expiry_minutes=-1,
        )

        # Should not raise when verification is disabled
        payload = decode_token(token, "test-secret", verify_exp=False)
        assert payload.user_id == "user-123"

    def test_extra_claims(self):
        """Test that extra claims are included in token."""
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            secret="test-secret",
            extra_claims={"custom_field": "custom_value"},
        )

        payload = decode_token(token, "test-secret")
        assert payload.raw.get("custom_field") == "custom_value"

    def test_invalid_token_format(self):
        """Test that invalid token format raises error."""
        with pytest.raises(TokenInvalidError):
            decode_token("not-a-valid-token", "test-secret")
