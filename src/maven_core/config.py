"""Configuration loading with environment variable substitution."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def substitute_env_vars(value: Any) -> Any:
    """Recursively substitute ${VAR_NAME} patterns with environment variables."""
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                raise ValueError(f"Environment variable {var_name} is not set")
            return env_value

        return ENV_VAR_PATTERN.sub(replace, value)
    elif isinstance(value, dict):
        return {k: substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [substitute_env_vars(v) for v in value]
    return value


class PasswordAuthConfig(BaseModel):
    """Password authentication settings."""

    min_length: int = 12
    require_special: bool = True


class JWTConfig(BaseModel):
    """JWT settings for built-in auth."""

    secret: str
    expiry_minutes: int = 15
    refresh_expiry_days: int = 30


class BuiltinAuthConfig(BaseModel):
    """Built-in authentication settings."""

    password: PasswordAuthConfig = Field(default_factory=PasswordAuthConfig)
    jwt: JWTConfig | None = None


class OIDCConfig(BaseModel):
    """OIDC authentication settings."""

    issuer: str
    audience: str
    jwks_uri: str | None = None  # Auto-derived from issuer if not provided


class AuthConfig(BaseModel):
    """Authentication configuration."""

    mode: str = "builtin"  # builtin | oidc
    builtin: BuiltinAuthConfig | None = None
    oidc: OIDCConfig | None = None


class RBACConfig(BaseModel):
    """RBAC configuration."""

    default_role: str = "user"
    roles: list[str] = Field(default_factory=lambda: ["admin", "user", "service"])


class SkillsConfig(BaseModel):
    """Skills configuration."""

    path: str = "./skills"
    cache_ttl_seconds: int = 300


class OAuthConnectorConfig(BaseModel):
    """OAuth settings for a connector."""

    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    scopes: list[str] = Field(default_factory=list)


class ConnectorConfig(BaseModel):
    """MCP connector configuration."""

    slug: str
    name: str
    mcp_server_url: str
    oauth: OAuthConnectorConfig


class FileStorageConfig(BaseModel):
    """File storage backend configuration."""

    backend: str = "local"
    # Backend-specific settings
    path: str | None = None  # For local backend
    bucket: str | None = None  # For R2/S3
    endpoint: str | None = None
    access_key: str | None = None
    secret_key: str | None = None


class KVStorageConfig(BaseModel):
    """KV storage backend configuration."""

    backend: str = "memory"
    # Backend-specific settings
    namespace_id: str | None = None
    api_token: str | None = None
    redis_url: str | None = None


class DatabaseStorageConfig(BaseModel):
    """Database backend configuration."""

    backend: str = "sqlite"
    # Backend-specific settings
    path: str | None = None  # For SQLite
    database_id: str | None = None  # For D1
    api_token: str | None = None
    connection_string: str | None = None  # For PostgreSQL


class StorageConfig(BaseModel):
    """Storage backends configuration."""

    files: FileStorageConfig = Field(default_factory=FileStorageConfig)
    kv: KVStorageConfig = Field(default_factory=KVStorageConfig)
    database: DatabaseStorageConfig = Field(default_factory=DatabaseStorageConfig)


class ProvisioningLimitsConfig(BaseModel):
    """Resource limits for sandboxes."""

    cpu_ms: int = 10000
    memory_mb: int = 128
    timeout_seconds: int = 30


class ProvisioningConfig(BaseModel):
    """Provisioning/sandbox backend configuration."""

    backend: str = "local"  # local | cloudflare
    account_id: str | None = None
    api_token: str | None = None
    limits: ProvisioningLimitsConfig = Field(default_factory=ProvisioningLimitsConfig)


class ControlPlaneConfig(BaseModel):
    """Control plane configuration (for multi-tenant mode)."""

    d1_database_id: str | None = None
    kv_namespace_id: str | None = None


class CloudflareConfig(BaseModel):
    """Cloudflare account configuration (for tenant provisioning)."""

    account_id: str | None = None
    api_token: str | None = None


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = "anthropic"  # anthropic | bedrock
    model: str = "claude-sonnet-4-20250514"
    region: str | None = None  # For Bedrock


class ServerConfig(BaseModel):
    """HTTP server configuration."""

    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: list[str] = Field(default_factory=list)


class Config(BaseModel):
    """Main configuration for maven-core."""

    tenant_id: str = "default"
    control_plane: ControlPlaneConfig = Field(default_factory=ControlPlaneConfig)
    cloudflare: CloudflareConfig = Field(default_factory=CloudflareConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rbac: RBACConfig = Field(default_factory=RBACConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    connectors: list[ConnectorConfig] = Field(default_factory=list)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    provisioning: ProvisioningConfig = Field(default_factory=ProvisioningConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        """Load configuration from a YAML or JSON file."""
        path = Path(path)
        with path.open() as f:
            if path.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(f)
            else:
                import json
                data = json.load(f)

        # Substitute environment variables
        data = substitute_env_vars(data)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Load configuration from a dictionary."""
        data = substitute_env_vars(data)
        return cls.model_validate(data)
