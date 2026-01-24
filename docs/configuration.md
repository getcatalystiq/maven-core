# Configuration Reference

Complete reference for maven-core configuration options.

## Configuration File

Maven-core supports YAML and JSON configuration files. Environment variables can be referenced using `${VAR_NAME}` syntax.

```yaml
# config.yaml
tenant_id: ${TENANT_ID}  # References environment variable
```

## Full Configuration Schema

```yaml
# Tenant identifier
tenant_id: my-tenant

# Authentication configuration
auth:
  mode: builtin  # builtin | oidc

  # Built-in authentication (password + JWT)
  builtin:
    password:
      min_length: 12
      require_special: true
    jwt:
      secret: ${JWT_SECRET}  # Required for builtin
      expiry_minutes: 15
      refresh_expiry_days: 30

  # OIDC authentication (external provider)
  oidc:
    issuer: https://auth.example.com
    audience: maven-core
    jwks_uri: https://auth.example.com/.well-known/jwks.json

# RBAC configuration
rbac:
  default_role: user
  roles:
    - admin
    - user
    - service

# Skills configuration
skills:
  path: ./skills        # Directory containing SKILL.md files
  cache_ttl_seconds: 300

# Connector configuration
connectors:
  - slug: github
    name: GitHub
    mcp_server_url: https://mcp.github.com
    oauth:
      client_id: ${GITHUB_CLIENT_ID}
      client_secret: ${GITHUB_CLIENT_SECRET}
      authorization_url: https://github.com/login/oauth/authorize
      token_url: https://github.com/login/oauth/access_token
      scopes:
        - repo
        - user

# Storage backends
storage:
  # File storage (for skills, transcripts)
  files:
    backend: local  # local | cloudflare_r2
    path: ./data/files  # For local backend

    # Cloudflare R2 settings
    # bucket: my-bucket
    # endpoint: ${R2_ENDPOINT}
    # access_key: ${R2_ACCESS_KEY}
    # secret_key: ${R2_SECRET_KEY}

  # Key-value storage (for metadata, cache)
  kv:
    backend: memory  # memory | cloudflare_kv

    # Cloudflare KV settings
    # namespace_id: ${KV_NAMESPACE_ID}
    # api_token: ${KV_API_TOKEN}

  # Database (for RBAC, OAuth tokens)
  database:
    backend: sqlite  # sqlite | cloudflare_d1

    # SQLite settings
    path: ./data/db.sqlite

    # Cloudflare D1 settings
    # database_id: ${D1_DATABASE_ID}
    # api_token: ${D1_API_TOKEN}

# Sandbox/provisioning configuration
provisioning:
  backend: local  # local | cloudflare

  # Resource limits
  limits:
    cpu_ms: 10000
    memory_mb: 128
    timeout_seconds: 30

  # Cloudflare settings
  # account_id: ${CF_ACCOUNT_ID}
  # api_token: ${CF_API_TOKEN}

# LLM configuration (Claude Agent SDK)
llm:
  provider: claude  # claude | mock
  backend: anthropic  # anthropic | bedrock | vertex
  model: claude-sonnet-4-20250514  # Optional, auto-detected
  allowed_tools:
    - Read
    - Write
    - Bash
    - Glob
    - Grep
  permission_mode: default  # default | acceptEdits | bypassPermissions

  # For AWS Bedrock:
  # backend: bedrock
  # model: us.anthropic.claude-opus-4-5-20251101-v1:0
  # aws_region: us-east-1
  # aws_profile: default

  # For Google Vertex AI:
  # backend: vertex
  # model: claude-sonnet-4@20250514

# HTTP server configuration
server:
  host: 0.0.0.0
  port: 8080
  cors_origins:
    - http://localhost:3000
```

## Storage Backends

### Files

| Backend | Description | Required Options |
|---------|-------------|------------------|
| `local` | Local filesystem | `path` |
| `cloudflare_r2` | Cloudflare R2 | `bucket`, `endpoint`, `access_key`, `secret_key` |

### Key-Value

| Backend | Description | Required Options |
|---------|-------------|------------------|
| `memory` | In-memory (development) | None |
| `cloudflare_kv` | Cloudflare KV | `namespace_id`, `api_token` |

### Database

| Backend | Description | Required Options |
|---------|-------------|------------------|
| `sqlite` | SQLite (development) | `path` |
| `cloudflare_d1` | Cloudflare D1 | `database_id`, `api_token` |

## Provisioning Backends

| Backend | Description | Required Options |
|---------|-------------|------------------|
| `local` | Subprocess-based (development) | None |
| `cloudflare` | Cloudflare Sandbox | `account_id`, `api_token` |

## LLM Backends

Maven-core uses the Claude Agent SDK with configurable backends.

| Backend | Description | Required Setup |
|---------|-------------|----------------|
| `anthropic` | Direct Anthropic API | `ANTHROPIC_API_KEY` env var |
| `bedrock` | AWS Bedrock | AWS credentials, Bedrock access enabled |
| `vertex` | Google Vertex AI | GCP credentials, project ID |

### LLM Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `provider` | LLM provider (`claude` or `mock`) | `claude` |
| `backend` | API backend (`anthropic`, `bedrock`, `vertex`) | `anthropic` |
| `model` | Model ID (backend-specific format) | Auto-detected |
| `allowed_tools` | Claude Code tools to enable | `["Read", "Glob", "Grep"]` |
| `cwd` | Working directory for file operations | None |
| `system_prompt` | Custom system prompt | None |
| `max_turns` | Maximum conversation turns | Unlimited |
| `permission_mode` | Tool permission mode | `default` |
| `aws_region` | AWS region (Bedrock only) | None |
| `aws_profile` | AWS profile (Bedrock only) | None |

For detailed backend configuration, see [Multi-Backend LLM Configuration](solutions/configuration-guides/multi-backend-llm-configuration.md).

## Environment Variables

Common environment variables:

```bash
# Required
JWT_SECRET=your-jwt-secret

# LLM - Anthropic API (default)
ANTHROPIC_API_KEY=sk-ant-...

# LLM - AWS Bedrock (if using backend: bedrock)
# AWS_REGION=us-east-1
# AWS_PROFILE=default
# Or use IAM role, ~/.aws/credentials

# LLM - Google Vertex AI (if using backend: vertex)
# GOOGLE_CLOUD_PROJECT=your-project-id
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Cloudflare (if using)
CF_ACCOUNT_ID=your-account-id
CF_API_TOKEN=your-api-token
R2_ENDPOINT=https://your-r2-endpoint
R2_ACCESS_KEY=your-access-key
R2_SECRET_KEY=your-secret-key
KV_NAMESPACE_ID=your-kv-namespace
D1_DATABASE_ID=your-d1-database

# OAuth connectors
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
```

## Programmatic Configuration

You can also configure maven-core programmatically:

```python
from maven_core import Agent

agent = Agent.from_dict({
    "tenant_id": "my-tenant",
    "storage": {
        "files": {"backend": "local", "path": "./data"},
        "kv": {"backend": "memory"},
        "database": {"backend": "sqlite", "path": "./db.sqlite"},
    },
    "provisioning": {"backend": "local"},
})
```
