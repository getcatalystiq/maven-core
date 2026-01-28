# Maven Core

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A TypeScript framework for building and managing AI agents on Cloudflare.

## Features

- **Multi-tenancy** - Isolated resources per tenant with control plane management
- **Authentication** - Built-in password auth with RS256 JWT tokens
- **RBAC** - Role-based access control with skill filtering
- **Skills** - Markdown-based skill definitions with role restrictions
- **MCP Connectors** - OAuth-secured connections to MCP servers
- **Claude Agent SDK** - Powered by Anthropic's official agent framework
- **Cloudflare-native** - Workers + Durable Objects + R2 + KV + D1

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client Request                           │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│                 Cloudflare Worker (Control Plane)                │
│  • Routes requests        • Auth (JWT RS256)                    │
│  • Admin endpoints        • Skills/Connectors CRUD              │
│  • Tenant provisioning    • Rate limiting                       │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Durable Object (Per-Tenant)                   │
│  • Manages sandbox lifecycle                                     │
│  • Session state persistence                                     │
│  • Loads skills & connectors config                             │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Cloudflare Sandbox (Agent)                    │
│  • Claude Agent SDK execution                                    │
│  • Skills (from R2)                                              │
│  • MCP servers                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Node.js 20+
- Docker
- Bun (for agent development)

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/maven-core.git
cd maven-core

# First-time setup (installs deps, generates keys, runs migrations)
npm run setup

# Start development servers
npm run dev:start
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed setup instructions.

## Development

### Control Plane (Cloudflare Worker)

```bash
cd packages/control-plane

# Run locally
npm run dev       # Port 8787

# Deploy
npm run deploy
```

### Tenant Worker (Cloudflare Worker)

```bash
# Local development
cd packages/tenant-worker
npm run dev       # Port 8788

# Deploy (use tenant CLI)
npm run tenant deploy <slug>
```

### Agent (Container)

```bash
# Run in Docker (recommended)
docker compose up agent     # Port 8080

# View logs
docker compose logs -f agent
```

## Configuration

### Local Development

The setup script generates `.dev.vars` files with local development keys. For production, set secrets in Cloudflare:

```bash
cd packages/control-plane

# Required secrets
npx wrangler secret put JWT_PRIVATE_KEY
npx wrangler secret put JWT_PUBLIC_KEY
npx wrangler secret put INTERNAL_API_KEY
```

### Cloudflare Resources

Copy the example wrangler configs and fill in your resource IDs:

```bash
cp packages/control-plane/wrangler.toml.example packages/control-plane/wrangler.toml
cp packages/tenant-worker/wrangler.toml.example packages/tenant-worker/wrangler.toml
```

## API Endpoints

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | POST | Login with email/password |
| `/auth/register` | POST | Register new user |
| `/auth/refresh` | POST | Refresh access token |
| `/.well-known/jwks.json` | GET | Public keys for JWT verification |

### Admin

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/users` | GET/POST | List/create users |
| `/admin/users/:id` | GET/PATCH/DELETE | Get/update/delete user |
| `/admin/tenants` | GET/POST | List/create tenants |
| `/admin/skills` | GET/POST | List/create skills |
| `/admin/connectors` | GET/POST | List/create MCP connectors |

### Chat

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | Send message, get response |
| `/chat/stream` | POST | Send message, stream response (SSE) |

## Project Structure

```
packages/
├── shared/           # Shared types, crypto, validation
│   └── src/
│       ├── types/    # TypeScript interfaces
│       ├── crypto/   # JWT, password hashing
│       └── validation/ # Zod schemas
│
├── control-plane/    # Cloudflare Worker (Admin API)
│   └── src/
│       ├── routes/   # API endpoints
│       ├── middleware/ # Auth, rate limiting
│       └── services/ # Business logic
│
├── tenant-worker/    # Cloudflare Worker (Per-Tenant)
│   └── src/
│       ├── middleware/ # JWT auth
│       └── durable-objects/ # TenantAgent
│
└── agent/            # Agent container
    └── src/
        ├── routes/   # HTTP handlers
        ├── skills/   # Skill loading
        └── mcp/      # MCP configuration
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## License

[MIT](LICENSE)
