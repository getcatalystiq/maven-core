# Quick Start Guide

Get started with maven-core in under 5 minutes.

## Installation

```bash
pip install maven-core
```

## Basic Usage

### Create a Configuration File

Create `config.yaml`:

```yaml
tenant_id: my-tenant

auth:
  mode: builtin
  builtin:
    jwt:
      secret: your-secret-key-here
      expiry_minutes: 60

storage:
  files:
    backend: local
    path: ./data/files

  kv:
    backend: memory

  database:
    backend: sqlite
    path: ./data/db.sqlite

provisioning:
  backend: local

server:
  host: 0.0.0.0
  port: 8080
```

### Start the Server

```python
from maven_core import Agent

agent = Agent.from_config("config.yaml")
agent.serve()
```

Or from the command line:

```bash
python -c "from maven_core import Agent; Agent.from_config('config.yaml').serve()"
```

### Use the API

Send a chat message:

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!", "user_id": "user-123"}'
```

Stream a response:

```bash
curl -X POST http://localhost:8080/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!", "user_id": "user-123"}'
```

### Direct Python Usage

```python
import asyncio
from maven_core import Agent

async def main():
    agent = Agent.from_config("config.yaml")

    # Single response
    response = await agent.chat(
        message="Hello!",
        user_id="user-123",
    )
    print(response.content)

    # Streaming
    async for chunk in agent.stream(
        message="Tell me a story",
        user_id="user-123",
    ):
        print(chunk.content, end="", flush=True)

asyncio.run(main())
```

## Context Manager

Use the async context manager for proper cleanup:

```python
async with Agent.from_config("config.yaml") as agent:
    response = await agent.chat(message="Hello", user_id="user-123")
```

## Next Steps

- [Configuration Reference](./configuration.md) - Full configuration options
- [Authentication Guide](./authentication.md) - Set up authentication
- [API Reference](./api-reference.md) - Complete API documentation
