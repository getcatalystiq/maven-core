# Maven Core

A modular, open-source Python framework for building and managing AI agents.

## Features

- **Multi-tenancy** - Isolated resources per tenant with control plane management
- **Authentication** - Built-in password auth or OIDC integration
- **RBAC** - Role-based access control with skill filtering
- **Skills** - Markdown-based skill definitions with role restrictions
- **MCP Connectors** - OAuth-secured connections to MCP servers
- **Cloudflare-first** - Default deployment on Workers + Durable Objects + R2 + KV + D1
- **Cloud-agnostic** - Protocol-based interfaces for storage, database, and sandboxes

## Installation

```bash
pip install maven-core
```

## Quick Start

### 1. Create a configuration file

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your settings
```

### 2. Start the server

```python
from maven_core import Agent

agent = Agent.from_config("config.yaml")
agent.serve(port=8080)
```

### 3. Or use directly in code

```python
from maven_core import Agent

agent = Agent.from_config("config.yaml")

# Single response
response = await agent.chat(
    message="Hello!",
    user_id="user-123",
)
print(response.content)

# Streaming
async for chunk in agent.stream(message="Hello!", user_id="user-123"):
    print(chunk.content, end="")
```

## Configuration

Maven Core uses YAML configuration with environment variable substitution:

```yaml
auth:
  mode: builtin
  builtin:
    jwt:
      secret: ${JWT_SECRET}  # Reads from environment

storage:
  files:
    backend: local
    path: ./data/files
```

See `config.example.yaml` for all options.

## Deployment Modes

### Standalone (Development)

Run as a Python ASGI server with uvicorn:

```bash
python -c "from maven_core import Agent; Agent.from_config('config.yaml').serve()"
```

### Cloudflare (Production)

Deploy as a Cloudflare Worker with Durable Objects:

```bash
cd worker
npm install
npm run deploy
```

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              maven-core                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  Public API                                                              │
│  ├── Agent.from_config()    - Load agent from YAML/JSON config          │
│  ├── Agent.serve()          - Start HTTP server (uvicorn)               │
│  ├── Agent.chat()           - Direct chat invocation                    │
│  └── Agent.stream()         - Streaming chat invocation                 │
├─────────────────────────────────────────────────────────────────────────┤
│  Core Components                                                         │
│  ├── auth/         - AuthManager (password or OIDC)                     │
│  ├── rbac/         - PermissionManager (roles, skill access)            │
│  ├── skills/       - SkillLoader (SKILL.md parsing, role filtering)     │
│  ├── connectors/   - ConnectorManager (OAuth flow, MCP integration)     │
│  └── provisioning/ - SandboxManager (code execution)                    │
├─────────────────────────────────────────────────────────────────────────┤
│  Protocol Interfaces                                                     │
│  ├── FileStore     - put/get/delete/list for files                      │
│  ├── KVStore       - get/set/delete for metadata                        │
│  ├── Database      - SQL operations                                      │
│  └── SandboxBackend- create/execute/destroy sandboxes                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## License

MIT
