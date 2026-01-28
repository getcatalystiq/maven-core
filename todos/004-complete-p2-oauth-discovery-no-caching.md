---
status: complete
priority: p2
issue_id: "004"
tags: [code-review, performance, oauth]
dependencies: []
---

# OAuth Discovery Not Cached

## Problem Statement

The OAuth initiation endpoints fetch MCP server metadata on every request:

```typescript
// packages/control-plane/src/services/connectors.ts:21-23
const wellKnownUrl = new URL('/.well-known/oauth-authorization-server', mcpServerUrl);
const response = await fetch(wellKnownUrl.toString(), { ... });
```

This external fetch occurs on the critical path of every OAuth initiation, adding 50-500ms latency.

**Why this matters:**
- OAuth server metadata (authorization_endpoint, token_endpoint) is stable
- Redundant external calls on every initiation
- No timeout specified (defaults to 30s which could hang the request)
- MCP server availability becomes a hard dependency

## Findings

**From performance-oracle agent:**
- "BLOCKING EXTERNAL REQUEST" on critical path
- "No Caching of Discovery Metadata"
- Request timeline: D1 (~5-10ms) → External fetch (50-500ms) → KV (~5ms)
- "No circuit breaker or fallback"

## Proposed Solutions

### Solution A: Cache discovery in KV (Recommended)

Cache OAuth metadata in KV with reasonable TTL (1 hour):

```typescript
const cacheKey = `oauth_discovery:${mcpServerUrl}`;
let metadata = await kv.get(cacheKey, 'json');
if (!metadata) {
  metadata = await fetchDiscovery(mcpServerUrl);
  await kv.put(cacheKey, JSON.stringify(metadata), { expirationTtl: 3600 });
}
```

**Pros:** Dramatically reduces latency after first call, resilient to temporary server issues
**Cons:** Needs cache invalidation strategy if endpoints change
**Effort:** Medium (1-2 hours)
**Risk:** Low

### Solution B: Add timeout to fetch

Add a 5-second timeout to the discovery fetch:

```typescript
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 5000);
const response = await fetch(url, { signal: controller.signal });
```

**Pros:** Prevents request hanging
**Cons:** Doesn't reduce latency or redundant calls
**Effort:** Small
**Risk:** Low

### Solution C: Cache in connector record (database)

Store discovered endpoints in connector metadata in D1 on first use.

**Pros:** Persists across worker restarts
**Cons:** Requires migration, stale data concerns
**Effort:** Medium
**Risk:** Medium

## Recommended Action

<!-- Filled during triage -->

## Technical Details

**Affected files:**
- `packages/control-plane/src/services/connectors.ts` (discoverOAuthEndpoints)
- `packages/control-plane/src/routes/widget/connectors.ts`
- `packages/control-plane/src/routes/oauth/authorize.ts`

## Acceptance Criteria

- [ ] OAuth discovery has timeout (prevents hanging)
- [ ] Repeated initiations for same connector are faster (if caching added)
- [ ] Cache invalidation strategy documented

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-28 | Created during code review | External fetch is main latency bottleneck |

## Resources

- RFC 8414: OAuth 2.0 Authorization Server Metadata
- Discovery URL: `/.well-known/oauth-authorization-server`
