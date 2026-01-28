---
status: complete
priority: p2
issue_id: "005"
tags: [code-review, security, oauth]
dependencies: []
---

# Redirect URI Validation Bypassable via Worker URL Variants

## Problem Statement

The same-origin check for redirect URI uses `c.req.url`:

```typescript
// packages/control-plane/src/routes/widget/connectors.ts:130-131
const requestOrigin = new URL(c.req.url).origin;
const redirectOrigin = new URL(redirectUri).origin;
```

Cloudflare Workers can be accessed via multiple origins:
- Custom domain: `https://api.example.com`
- Workers.dev: `https://project.workers.dev`
- Other bound domains

An attacker could access the API via one origin and provide a redirect URI on that same origin, potentially redirecting tokens to a controlled endpoint.

**Why this matters:**
- Open redirect vulnerability in OAuth flow
- Could lead to token theft
- Validation logic has false sense of security

## Findings

**From security-sentinel agent:**
- Severity: HIGH
- "Redirect URI validation is bypassable via Cloudflare Worker URL variants"
- Exploitability: Medium (depends on domain configuration)

## Proposed Solutions

### Solution A: Allowlist of valid redirect URIs (Recommended)

Maintain explicit allowlist of valid redirect base URLs:

```typescript
const ALLOWED_REDIRECT_ORIGINS = [
  'https://api.maven.example.com',  // Production
  'http://localhost:8787',           // Local dev
];

if (!ALLOWED_REDIRECT_ORIGINS.includes(redirectOrigin)) {
  throw new HTTPException(400, { message: 'Invalid redirect_uri' });
}
```

**Pros:** Explicit security, no ambiguity
**Cons:** Requires configuration management
**Effort:** Medium
**Risk:** Low

### Solution B: Use configured origin from env

Compare against a configured `API_ORIGIN` environment variable:

```typescript
const allowedOrigin = c.env.API_ORIGIN || new URL(c.req.url).origin;
```

**Pros:** Single source of truth, configurable
**Cons:** Requires env var setup
**Effort:** Small
**Risk:** Low

### Solution C: Validate redirect path is our callback endpoint

Instead of origin, validate the full redirect URI matches our callback pattern:

```typescript
const expectedCallback = `/oauth/${connectorId}/callback`;
const redirectPath = new URL(redirectUri).pathname;
if (redirectPath !== expectedCallback) {
  throw new HTTPException(400, { message: 'Invalid redirect_uri' });
}
```

**Pros:** Path validation is more specific
**Cons:** Still allows any origin with correct path
**Effort:** Small
**Risk:** Medium

## Recommended Action

<!-- Filled during triage -->

## Technical Details

**Affected files:**
- `packages/control-plane/src/routes/widget/connectors.ts` (lines 129-140)
- `packages/control-plane/src/routes/oauth/authorize.ts` (validateRedirectUri function)

## Acceptance Criteria

- [ ] Redirect URI validation cannot be bypassed via alternate worker domains
- [ ] Valid production and development redirects still work
- [ ] Security test confirms bypass is blocked

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-28 | Created during code review | Same-origin check is insufficient for multi-domain workers |

## Resources

- OAuth 2.0 Security Best Practices: Redirect URI validation
- Cloudflare Workers: Custom domains and routes
