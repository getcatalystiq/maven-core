# Maven Core

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
│                    Cloudflare Worker (Controller)                │
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

## Installation

```bash
npm install
npm run build
```

## Development

### Controller (Cloudflare Worker)

```bash
cd packages/controller

# Run locally
npm run dev

# Deploy
npm run deploy
```

### Agent (Container)

```bash
cd packages/agent

# Run locally
npm run dev

# Build Docker image
docker build -t maven-agent .
```

## Configuration

Set secrets in Cloudflare:

```bash
cd packages/controller

# Required secrets
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put JWT_PRIVATE_KEY
npx wrangler secret put JWT_PUBLIC_KEY
npx wrangler secret put INTERNAL_API_KEY
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
├── controller/       # Cloudflare Worker
│   └── src/
│       ├── routes/   # API endpoints
│       ├── middleware/ # Auth, rate limiting
│       ├── services/ # Business logic
│       └── durable-objects/
│
└── agent/            # Agent container
    └── src/
        ├── routes/   # HTTP handlers
        ├── skills/   # Skill loading
        └── mcp/      # MCP configuration
```

## License

MIT
