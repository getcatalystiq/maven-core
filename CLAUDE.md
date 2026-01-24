# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (dev mode)
uv pip install -e ".[dev]"

# Run all tests with coverage
pytest

# Run a single test file
pytest tests/test_auth/test_jwt.py

# Run a specific test
pytest tests/test_auth/test_jwt.py::test_jwt_encode_decode -v

# Type checking
mypy src/

# Linting
ruff check src/

# Auto-fix lint issues
ruff check src/ --fix
```

## Architecture

Maven-core is a modular Python framework for building AI agents with multi-tenancy support.

### Core Entry Point

The `Agent` class (`src/maven_core/agent.py`) is the primary interface:
- `Agent.from_config(path)` - Load from YAML/JSON config
- `Agent.from_dict(config)` - Load from dictionary
- `agent.serve()` - Start HTTP server (uvicorn)
- `agent.chat()` / `agent.stream()` - Direct invocation

Backends are lazily initialized on first use via `_ensure_initialized()`.

### Protocol-Based Backend System

All storage and execution backends implement Protocol interfaces (`src/maven_core/protocols/`):

| Protocol | Purpose | Methods |
|----------|---------|---------|
| `FileStore` | File storage (R2, S3, local) | `put`, `get`, `head`, `delete`, `list` |
| `KVStore` | Key-value (KV, Redis, memory) | `get`, `set`, `delete`, `list` |
| `Database` | SQL (D1, SQLite, Postgres) | `execute`, `execute_many`, `transaction` |
| `SandboxBackend` | Code execution | `create`, `execute`, `destroy` |

### Plugin Discovery

Backends are registered via Python entry points in `pyproject.toml` and discovered at runtime by `src/maven_core/plugins.py`:
- `maven_core.backends.files` - File storage backends
- `maven_core.backends.kv` - KV store backends
- `maven_core.backends.database` - Database backends
- `maven_core.backends.sandbox` - Sandbox backends

### Module Structure

- `auth/` - AuthManager with password (argon2id) or OIDC authentication
- `rbac/` - PermissionManager for role-based skill access control
- `skills/` - SkillLoader parses SKILL.md files with YAML frontmatter for role filtering
- `connectors/` - ConnectorManager handles OAuth flows for MCP server connections
- `provisioning/` - SandboxManager for tenant sandboxes and code execution
- `sessions/` - Session storage and transcript management
- `server/` - Starlette app with SSE streaming, middleware (auth, rate limiting, CORS)
- `observability.py` - Structured logging with context vars, metrics emission
- `caching.py` - TTLCache for in-memory caching
- `rate_limiting.py` - SlidingWindowRateLimiter and CompositeRateLimiter

### Configuration

YAML config with `${VAR}` environment variable substitution. Key sections:
- `auth.mode`: `builtin` (password + JWT) or `oidc` (external provider)
- `storage.files/kv/database`: Backend selection with backend-specific options
- `provisioning.backend`: `local` (subprocess) or `cloudflare` (sandbox)

### HTTP Server

Starlette-based server (`src/maven_core/server/`) with:
- `/chat` - JSON response
- `/chat/stream` - SSE streaming
- `/invocations` - SageMaker-compatible alias for streaming
- Middleware chain: CORS → Rate Limiting → Authentication
