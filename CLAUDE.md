# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# First-time setup (generates keys, creates .dev.vars, runs migrations)
npm run setup

# Install dependencies
npm install

# Build all packages
npm run build

# Development mode (all packages)
npm run dev

# Type checking
npm run typecheck

# Run tests
npm run test

# Lint
npm run lint
```

### Control Plane (Cloudflare Worker)

```bash
# Development server
cd packages/control-plane && npm run dev  # Port 8787

# Deploy to Cloudflare
cd packages/control-plane && npm run deploy
```

### Database Migrations

```bash
# Check migration status
npm run migrate:status

# Apply pending migrations (local)
npm run migrate

# Apply pending migrations (remote/production)
npm run migrate:remote

# Create a new migration
npm run migrate:create <name>
# Example: npm run migrate:create add_audit_logs
```

Migrations are stored in `packages/control-plane/migrations/` with timestamp-based filenames.
The `_migrations` table tracks which migrations have been applied.

### Tenant Worker (Cloudflare Worker)

```bash
# Development server
cd packages/tenant-worker && npm run dev  # Port 8788

# Deploy to Cloudflare
cd packages/tenant-worker && npm run deploy
```

### Agent (Docker Container)

The agent **always runs in Docker** to ensure consistent environment with the Claude CLI and proper isolation.

```bash
# Start agent (Docker) - preferred
docker compose up -d agent          # Port 8080

# View logs
docker compose logs -f agent

# Rebuild after code changes
docker compose up -d --build agent

# Stop agent
docker compose down agent

# Build image only (without running)
docker compose build agent
```

Configuration is loaded from `packages/agent/.env` which should contain:
- `CLAUDE_CODE_USE_BEDROCK=1` - Use AWS Bedrock
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` - AWS credentials
- `AWS_REGION` - AWS region (default: us-east-1)
- Or `ANTHROPIC_API_KEY` for direct Anthropic API

## Architecture

Maven-core is a TypeScript framework for building AI agents with multi-tenancy support, deployed on Cloudflare.

### Project Structure

```
/packages
├── shared/              # Shared types, crypto, validation
│   └── src/
│       ├── types/       # TypeScript type definitions
│       ├── crypto/      # JWT (RS256), password hashing
│       └── validation/  # Zod schemas
│
├── control-plane/       # Cloudflare Worker (Control Plane)
│   └── src/             # Admin, auth, tenant management, skills/connectors CRUD
│       ├── routes/      # Auth, admin, OAuth, internal endpoints
│       ├── middleware/  # JWT auth, rate limiting
│       └── services/    # Database, skills, connectors (D1/KV/R2)
│
├── tenant-worker/       # Cloudflare Worker (Per-Tenant Chat Router)
│   └── src/             # Lightweight chat routing to DO → Agent
│       ├── middleware/  # JWT auth (stateless, public key only)
│       └── durable-objects/ # TenantAgent (manages sandboxes)
│
└── agent/               # Agent Container (Sandbox)
    └── src/
        ├── routes/      # Chat, stream, sessions
        ├── skills/      # Skill loader (SKILL.md parser)
        └── mcp/         # MCP server configuration
```

### Key Technologies

- **Claude Agent SDK** (`@anthropic-ai/claude-agent-sdk@0.2.12`) - Agent execution
- **Hono** - HTTP routing framework
- **Cloudflare Workers** - Serverless compute
- **Cloudflare D1** - SQLite database
- **Cloudflare KV** - Key-value storage
- **Cloudflare R2** - Object storage (skill files)
- **Durable Objects** - Per-tenant state management
- **Cloudflare Containers** - Sandbox execution environment

### Request Flow

```
┌────────────────────────────────────┐     ┌─────────────────────────────┐
│  Control Plane Worker              │     │  Tenant Worker              │
│  (api.maven.example.com)           │     │  (*.workers.dev or custom)  │
│                                    │     │                             │
│  Routes:                           │     │  Routes:                    │
│  • /auth/*                         │     │  • /chat                    │
│  • /admin/*                        │     │  • /chat/stream             │
│  • /oauth/*                        │     │  • /sessions                │
│  • /.well-known/jwks.json          │     │  • /health                  │
│  • /internal/* (for DO config)     │     │                             │
│                                    │     │  ~150 lines (lightweight)   │
│  Bindings: DB (D1), KV, FILES (R2) │     │  Bindings: TENANT_AGENT DO  │
└────────────────────────────────────┘     └─────────────────────────────┘
         │                                              │
         │  /internal/sandbox-config                    │
         └──────────────────────────────────────────────┤
                                                        ▼
                                           ┌─────────────────────────────┐
                                           │  TenantAgent DO             │
                                           │  (per tenant)               │
                                           │                             │
                                           │  • Fetches config from      │
                                           │    Control Plane /internal  │
                                           │  • Proxies to Sandbox/Agent │
                                           └─────────────────────────────┘
```

1. Client → Tenant Worker (validates JWT stateless)
2. Tenant Worker routes to Durable Object per tenant
3. DO fetches skills/connectors from Control Plane's `/internal` API
4. DO manages sandbox lifecycle
5. Sandbox runs Claude Agent SDK with skills/connectors

### Authentication

- RS256 JWT tokens for API authentication
- Password hashing with scrypt (Web Crypto API compatible)
- JWKS endpoint for public key distribution
- OAuth support for MCP connectors
- Tenant Worker validates tokens using public key only (stateless)

### Skills & Connectors

Skills are stored in R2 with metadata in D1:
- `skills/{tenant_id}/{skill_name}/SKILL.md` - Skill definition
- YAML frontmatter for roles, tools, description

Connectors (MCP servers) are stored in D1:
- OAuth tokens stored in KV
- Supports stdio, SSE, and HTTP MCP transports

### Development Setup

**First-time setup:**

```bash
npm run setup
```

This script:
1. Installs all dependencies
2. Builds all packages
3. Generates RS256 JWT keypair (stored in `.keys/`)
4. Creates `.dev.vars` files for both workers with the keys
5. Initializes the D1 database with migrations

**Start all servers (recommended):**

```bash
npm run dev:start   # Starts control-plane, tenant-worker (wrangler), and agent (Docker)
npm run dev:status  # Check server status
npm run dev:logs    # Tail all logs (Ctrl+C to exit)
npm run dev:stop    # Stop all servers
npm run dev:restart # Restart all servers
```

**Start servers individually:**

```bash
# Terminal 1: Control plane (wrangler)
cd packages/control-plane && npm run dev  # Port 8787

# Terminal 2: Tenant worker (wrangler)
cd packages/tenant-worker && npm run dev  # Port 8788

# Terminal 3: Agent (Docker - always use Docker!)
docker compose up agent                    # Port 8080
```

**For Claude Code sessions**, use background tasks:

```bash
# Run each as a separate background task:
cd packages/control-plane && npm run dev  # Port 8787 (run_in_background: true)
cd packages/tenant-worker && npm run dev  # Port 8788 (run_in_background: true)
docker compose up agent                    # Port 8080 (run_in_background: true)
```

Use `/tasks` to view running tasks.

**Quick test:**

```bash
# Register a user
curl -X POST http://localhost:8787/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@test.com","password":"DevPass123@","name":"Dev User"}'

# Login to get a token
curl -X POST http://localhost:8787/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@test.com","password":"DevPass123@"}'

# Use token for chat (tenant worker)
curl -X POST http://localhost:8788/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello"}'
```
