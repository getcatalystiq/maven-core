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

**⚠️ CRITICAL: ALWAYS use `npm run tenant deploy <slug>` to deploy tenant workers.**

**NEVER run `wrangler deploy` directly in packages/tenant-worker - it will not work.**

```bash
# PRODUCTION DEPLOYMENT - THE ONLY WAY
npm run tenant deploy <slug>              # Deploy tenant worker with container
npm run tenant deploy <slug> --dry-run    # Preview deployment config

# Use specific image version
AGENT_IMAGE_TAG=v1.0.0 npm run tenant deploy <slug>

# Other tenant commands
npm run tenant dev <slug>                 # Local dev with tenant config
npm run tenant list                       # List all tenants

# Examples
npm run tenant deploy easycarnet
npm run tenant deploy easycarnet --dry-run
AGENT_IMAGE_TAG=v2.0.0 npm run tenant deploy easycarnet
```

**Why must you use the tenant CLI?**
- Container config is dynamically injected per tenant (name: `maven-tenant-{slug}-sandbox`)
- The base `wrangler.toml` has NO container config - direct deploy will fail
- Image tag is configurable via `AGENT_IMAGE_TAG` environment variable
- Tenant-specific vars (ID, slug) are injected automatically

**Environment variables for deployment:**
| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_IMAGE_TAG` | `v1.0.0` | Container image tag to deploy |
| `CF_ACCOUNT_ID` | (hardcoded) | Cloudflare account ID |
| `CONTROL_PLANE_URL` | `http://localhost:8787` | Control plane for tenant config |

**Local development only (no containers):**
```bash
cd packages/tenant-worker && npm run dev  # Port 8788
```

The tenant CLI fetches config from the control plane's `/internal/tenant/:slug` endpoint,
generates a temporary wrangler config with container injected, and deploys. Config is
cached in `packages/tenant-worker/.tenant-config/` for offline development.

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
- **Cloudflare R2** - Object storage (skill files, agent logs)
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

### Agent Container Logs

Agent containers write structured logs that are collected by the Durable Object and stored in R2 for observability and debugging.

**How it works:**

1. Agent writes logs to stdout (redirected to `/tmp/agent.log` in the container)
2. The TenantAgent DO periodically pulls new log lines from the container
3. Logs are buffered in memory (max 100 entries or 10 seconds)
4. Buffered logs are written to R2 as NDJSON files
5. Automatic 7-day retention cleanup

**Log storage format:**

Logs are stored at: `logs/{tenantId}/{YYYY-MM-DD}/{timestamp}.ndjson`

Each line contains a structured log entry:
```json
{"ts":"2026-01-27T10:15:30.123Z","level":"info","msg":"[TIMING] T+50ms: Agent started","tenant":"abc123"}
```

**Querying logs via Admin API:**

```bash
# List available log files for a tenant
curl "http://localhost:8787/admin/logs?tenantId=TENANT_ID&since=2026-01-01&limit=50" \
  -H "Authorization: Bearer $TOKEN"

# Read a specific log file
curl "http://localhost:8787/admin/logs/TENANT_ID/2026-01-27/1706345678123.ndjson" \
  -H "Authorization: Bearer $TOKEN"

# Search logs with filters
curl "http://localhost:8787/admin/logs/search?tenantId=TENANT_ID&query=error&level=error" \
  -H "Authorization: Bearer $TOKEN"

# Delete old logs (super admin only)
curl -X DELETE "http://localhost:8787/admin/logs?tenantId=TENANT_ID&before=2026-01-20" \
  -H "Authorization: Bearer $TOKEN"
```

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `tenantId` | Required. The tenant ID to query logs for |
| `since` | Filter logs after this date (YYYY-MM-DD) |
| `until` | Filter logs before this date (YYYY-MM-DD) |
| `limit` | Maximum number of results (default: 100) |
| `query` | Text search in log messages |
| `level` | Filter by level: `info`, `warn`, `error` |
| `sessionId` | Filter by chat session ID |

**Access control:**
- Super admins can view logs for any tenant
- Regular admins can only view their own tenant's logs
- Only super admins can delete logs

**Checking logs via R2 directly:**

```bash
# Download a specific log file (bucket/key as single path)
npx wrangler r2 object get "maven-files/logs/TENANT_ID/2026-01-27/1706345678123.ndjson" \
  --file /tmp/logs.ndjson --remote

# Or pipe directly to stdout
npx wrangler r2 object get "maven-files/logs/TENANT_ID/2026-01-27/1706345678123.ndjson" \
  --pipe --remote | jq .

# View log entries
cat /tmp/logs.ndjson | jq .
```

### Secrets Management (Cloudflare Secrets Store)

Shared secrets use Cloudflare Secrets Store for centralized management across workers.

**Local development:** Uses `.dev.vars` files with plain strings (created by `npm run setup`)

**Production:** Uses Secrets Store bindings (async access via `get()` method)

```typescript
// Code works with both local dev (string) and production (SecretBinding)
import { getSecret } from '@maven/shared';

const publicKey = await getSecret(env.JWT_PUBLIC_KEY);
```

**Current setup:**

| Secret | Source | control-plane | tenant-worker | maven-admin | maven-widget |
|--------|--------|---------------|---------------|-------------|--------------|
| `maven-jwt-public-key` | Secrets Store | ✅ | ✅ | ✅ | ✅ |
| `maven-internal-api-key` | Secrets Store | ✅ | ✅ | ✅ | - |
| `maven-cf-account-id` | Secrets Store | ✅ | - | - | - |
| `maven-cf-api-token` | Secrets Store | ✅ | - | - | - |
| `JWT_PRIVATE_KEY` | Per-worker | ✅ | - | - | - |

Store ID: `4f06aa96622946a4b336737a727e9354`

**Note:** JWT_PRIVATE_KEY exceeds Secrets Store size limit (~1.7KB > 1KB limit), so it remains a per-worker secret for control-plane only.

### Tenant Provisioning

Pro and Enterprise tier tenants get dedicated workers with Durable Objects and Sandbox containers.

**Prerequisites for provisioning:**

1. **Cloudflare credentials** in Secrets Store (control-plane needs these to deploy workers):
   ```bash
   # Add CF_ACCOUNT_ID
   npx wrangler secrets-store secret create 4f06aa96622946a4b336737a727e9354 \
     --name maven-cf-account-id --scopes workers --remote

   # Add CF_API_TOKEN (needs Workers write permissions)
   npx wrangler secrets-store secret create 4f06aa96622946a4b336737a727e9354 \
     --name maven-cf-api-token --scopes workers --remote
   ```

2. **Container image** must exist in the registry:
   ```bash
   # Build and push agent container (uses cloudflare/sandbox base image)
   ./scripts/push-agent.sh v1.0.0

   # Verify image exists
   npx wrangler containers images list
   ```

   The image tag used for provisioning is controlled by `AGENT_IMAGE_TAG` in
   `packages/control-plane/wrangler.toml` (defaults to `v1.0.0`).

   **Releasing a new agent version:**
   ```bash
   # 1. Build and push the new version
   ./scripts/push-agent.sh v1.1.0

   # 2. Update wrangler.toml with the new tag
   # Edit packages/control-plane/wrangler.toml: AGENT_IMAGE_TAG = "v1.1.0"

   # 3. Redeploy control-plane
   cd packages/control-plane && npm run deploy
   ```

   New tenants will use the updated image. Existing tenants keep their
   deployed version until their worker is redeployed.

3. **Tenant worker bundle** in R2 (for dedicated worker deployments):
   ```bash
   # Build and upload tenant-worker bundle
   cd packages/tenant-worker && npm run build
   npx wrangler r2 object put maven-files/bundles/tenant-worker.js \
     --file dist/index.js --remote
   ```

**Provision a tenant via API:**

```bash
# Get admin JWT token, then:
curl -X POST https://maven-control-plane.tools-7b7.workers.dev/admin/tenants/provision \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"TenantName","slug":"tenant-slug","tier":"pro"}'

# Check provisioning status
curl https://maven-control-plane.tools-7b7.workers.dev/admin/tenants/provision/$JOB_ID \
  -H "Authorization: Bearer $TOKEN"
```

**What gets created for pro/enterprise tiers:**
- D1 tenant record with settings
- Dedicated worker: `maven-tenant-{slug}`
- Worker secrets (JWT_PUBLIC_KEY, INTERNAL_API_KEY)
- Sandbox container configuration

**Adding secrets for new projects (maven-admin, maven-widget):**

```toml
# In wrangler.toml
[[secrets_store_secrets]]
binding = "JWT_PUBLIC_KEY"
store_id = "4f06aa96622946a4b336737a727e9354"
secret_name = "maven-jwt-public-key"

[[secrets_store_secrets]]
binding = "INTERNAL_API_KEY"
store_id = "4f06aa96622946a4b336737a727e9354"
secret_name = "maven-internal-api-key"
```

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
