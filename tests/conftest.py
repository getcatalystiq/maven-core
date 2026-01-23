"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_config_dict():
    """Sample configuration dictionary for testing."""
    return {
        "tenant_id": "test-tenant",
        "auth": {
            "mode": "builtin",
            "builtin": {
                "password": {"min_length": 8, "require_special": False},
                "jwt": {"secret": "test-secret-key-for-testing-only"},
            },
        },
        "storage": {
            "files": {"backend": "local", "path": "/tmp/maven-test/files"},
            "kv": {"backend": "memory"},
            "database": {"backend": "sqlite", "path": ":memory:"},
        },
        "provisioning": {"backend": "local"},
    }
