"""Tests for configuration loading."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from maven_core.config import Config, substitute_env_vars


class TestEnvSubstitution:
    """Tests for environment variable substitution."""

    def test_substitute_string(self):
        """Test substituting a string value."""
        os.environ["TEST_VAR"] = "hello"
        result = substitute_env_vars("${TEST_VAR}")
        assert result == "hello"

    def test_substitute_in_dict(self):
        """Test substituting values in a dictionary."""
        os.environ["TEST_KEY"] = "secret"
        data = {"key": "${TEST_KEY}", "other": "value"}
        result = substitute_env_vars(data)
        assert result == {"key": "secret", "other": "value"}

    def test_substitute_in_list(self):
        """Test substituting values in a list."""
        os.environ["TEST_ITEM"] = "item1"
        data = ["${TEST_ITEM}", "item2"]
        result = substitute_env_vars(data)
        assert result == ["item1", "item2"]

    def test_missing_env_var_raises(self):
        """Test that missing env vars raise ValueError."""
        if "NONEXISTENT_VAR" in os.environ:
            del os.environ["NONEXISTENT_VAR"]
        with pytest.raises(ValueError, match="NONEXISTENT_VAR"):
            substitute_env_vars("${NONEXISTENT_VAR}")

    def test_partial_substitution(self):
        """Test substituting part of a string."""
        os.environ["PREFIX"] = "prod"
        result = substitute_env_vars("${PREFIX}-database")
        assert result == "prod-database"


class TestConfigLoading:
    """Tests for configuration loading."""

    def test_from_dict(self, sample_config_dict):
        """Test loading config from dictionary."""
        config = Config.from_dict(sample_config_dict)
        assert config.tenant_id == "test-tenant"
        assert config.auth.mode == "builtin"
        assert config.storage.files.backend == "local"

    def test_from_yaml_file(self, sample_config_dict):
        """Test loading config from YAML file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(sample_config_dict, f)
            f.flush()

            config = Config.from_file(f.name)
            assert config.tenant_id == "test-tenant"

            Path(f.name).unlink()

    def test_defaults(self):
        """Test that defaults are applied."""
        config = Config.from_dict({})
        assert config.tenant_id == "default"
        assert config.auth.mode == "builtin"
        assert config.rbac.default_role == "user"
        assert config.storage.files.backend == "local"
        assert config.storage.kv.backend == "memory"
        assert config.storage.database.backend == "sqlite"

    def test_oidc_config(self):
        """Test OIDC configuration."""
        config = Config.from_dict({
            "auth": {
                "mode": "oidc",
                "oidc": {
                    "issuer": "https://auth.example.com",
                    "audience": "my-app",
                },
            },
        })
        assert config.auth.mode == "oidc"
        assert config.auth.oidc is not None
        assert config.auth.oidc.issuer == "https://auth.example.com"
