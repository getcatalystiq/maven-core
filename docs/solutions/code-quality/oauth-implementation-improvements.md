---
title: Widget connector security, performance, and code quality improvements
category: code-quality
tags:
  - oauth
  - pkce
  - widget-connectors
  - cloudflare-worker
  - code-deduplication
  - caching
  - input-validation
  - information-disclosure
  - redirect-uri-validation
  - uuid-validation
  - control-plane
module: packages/control-plane/src/routes/widget/connectors.ts
symptoms:
  - PKCE code duplicated across oauth/authorize.ts and widget/connectors.ts
  - Inconsistent PKCE behavior between oauth and widget routes
  - Missing typed responses causing potential type safety issues
  - 50-500ms latency on OAuth discovery fetch for every initiation
  - Redirect URI validation bypassable via alternate worker domains
  - Super-admin requests with empty tenantId caused unexpected behavior
  - Internal MCP server URLs exposed in error messages
  - Invalid connectorId UUIDs passed to database queries
root_cause: Initial implementation prioritized functionality over security hardening, performance optimization, and code maintainability
resolution_type: refactor
severity: high
date_documented: 2026-01-28
---

# Widget Connector OAuth Implementation Improvements

## Problem

The OAuth connector implementation in the control-plane had eight code review issues that needed to be addressed:

1. **PKCE Code Duplication** - The PKCE (Proof Key for Code Exchange) implementation was duplicated across multiple route files, violating the DRY principle and making maintenance difficult.

2. **PKCE Behavioral Inconsistency** - The `oauth/authorize.ts` route checked for server PKCE support before generating challenges, while `widget/connectors.ts` always generated PKCE regardless of server capabilities.

3. **Missing Typed Responses** - API responses were using inline object literals instead of shared type definitions, making the API contract unclear and type-unsafe.

4. **No OAuth Discovery Caching** - Every OAuth initiation performed a fresh discovery request to the MCP server's `.well-known/oauth-authorization-server` endpoint, causing unnecessary latency.

5. **No Redirect URI Validation** - The OAuth flow accepted any redirect URI from the same origin, but could be bypassed via alternate worker domains.

6. **Missing TenantId Validation** - Widget endpoints could be accessed by super-admins without a tenant context, potentially causing runtime errors.

7. **Information Disclosure** - Error messages exposed internal details about OAuth discovery failures and connector configurations to clients.

8. **Missing UUID Validation** - The `connectorId` path parameter was not validated, allowing potential injection attacks or confusing error messages.

## Root Cause

These issues arose from organic code growth without consistent patterns:

- **PKCE duplication** happened because two routes (`oauth/authorize.ts` and `widget/connectors.ts`) were developed at different times with copy-pasted implementations.
- **Behavioral inconsistency** occurred when the widget route was added without referencing the existing authorize route's conditional PKCE logic.
- **Missing typed responses** resulted from quick prototyping without defining shared contracts upfront.
- **No caching** was a performance oversight during initial implementation.
- **Security gaps** (redirect validation, UUID validation, info disclosure) were missed during initial review due to focus on functionality over security hardening.
- **TenantId validation** was missing because the widget routes assumed a standard user flow, not considering super-admin API access patterns.

## Solution

### 1. PKCE Code Centralization

Created a shared PKCE module at `packages/shared/src/crypto/pkce.ts`:

```typescript
/**
 * PKCE (Proof Key for Code Exchange) utilities for OAuth 2.0
 * RFC 7636: https://datatracker.ietf.org/doc/html/rfc7636
 */

export function base64UrlEncode(buffer: Uint8Array): string {
  let binary = '';
  for (let i = 0; i < buffer.length; i++) {
    binary += String.fromCharCode(buffer[i]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

export function generateCodeVerifier(): string {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return base64UrlEncode(array);
}

export async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return base64UrlEncode(new Uint8Array(digest));
}
```

### 2. Consistent PKCE Behavior

Both routes now conditionally add PKCE based on server support:

```typescript
// Add PKCE if supported by the authorization server
let codeVerifier: string | undefined;
if (oauthMetadata.code_challenge_methods_supported?.includes('S256')) {
  codeVerifier = generateCodeVerifier();
  const codeChallenge = await generateCodeChallenge(codeVerifier);
  authParams.set('code_challenge', codeChallenge);
  authParams.set('code_challenge_method', 'S256');
}
```

### 3. Typed Responses

Routes now use shared types from `@maven/shared`:

```typescript
import type { OAuthInitiateResponse, DisconnectResponse } from '@maven/shared';

const response: OAuthInitiateResponse = { authorizationUrl };
return c.json(response);

const response: DisconnectResponse = { disconnected: true };
return c.json(response);
```

### 4. OAuth Discovery Caching

Added `discoverOAuthEndpointsCached()` with 1-hour KV cache and 5-second timeout:

```typescript
export async function discoverOAuthEndpointsCached(
  kv: KVNamespace,
  mcpServerUrl: string
): Promise<OAuthServerMetadata | null> {
  const cacheKey = `oauth_discovery:${mcpServerUrl}`;

  // Check cache first
  const cached = await kv.get<OAuthServerMetadata>(cacheKey, 'json');
  if (cached) {
    return cached;
  }

  // Fetch fresh metadata (with 5s timeout)
  const metadata = await discoverOAuthEndpoints(mcpServerUrl);
  if (metadata) {
    // Cache for 1 hour
    await kv.put(cacheKey, JSON.stringify(metadata), { expirationTtl: 3600 });
  }

  return metadata;
}
```

### 5. Redirect URI Validation

Added allowlist-based validation using `CORS_ALLOWED_ORIGINS`:

```typescript
export function validateRedirectUri(env: EnvWithCors, redirectUri: string): boolean {
  try {
    const redirectUrl = new URL(redirectUri);
    const redirectOrigin = redirectUrl.origin;

    const defaultOrigins = [
      'http://localhost:8787',
      'http://localhost:8788',
      'http://127.0.0.1:8787',
      'http://127.0.0.1:8788',
    ];

    const allowedOriginsStr = env.CORS_ALLOWED_ORIGINS || '';
    const configuredOrigins = allowedOriginsStr
      ? allowedOriginsStr.split(',').map((o) => o.trim()).filter(Boolean)
      : [];

    const allowedOrigins = configuredOrigins.length > 0
      ? configuredOrigins
      : defaultOrigins;

    return allowedOrigins.includes(redirectOrigin);
  } catch {
    return false;
  }
}
```

### 6. TenantId Validation Middleware

Added middleware to require tenant context:

```typescript
app.use('*', async (c, next) => {
  const tenantId = c.get('tenantId');
  if (!tenantId) {
    throw new HTTPException(400, {
      message: 'Tenant context required. Super-admins must specify X-Tenant-Id header.',
    });
  }
  await next();
});
```

### 7. Information Disclosure Fix

Changed to generic error messages with server-side logging:

```typescript
// Log detailed error server-side
console.error(`OAuth discovery failed for connector ${connectorId}`);

// Return generic message to client
throw new HTTPException(400, {
  message: 'Connector MCP server does not support OAuth discovery',
});
```

### 8. UUID Validation

Added UUID regex validation for path parameters:

```typescript
const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

if (!UUID_REGEX.test(connectorId)) {
  throw new HTTPException(400, { message: 'Invalid connector ID format' });
}
```

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `packages/shared/src/crypto/pkce.ts` | Added | Centralized PKCE utilities |
| `packages/shared/src/crypto/index.ts` | Modified | Export PKCE module |
| `packages/control-plane/src/services/connectors.ts` | Modified | Added caching, redirect validation, timeout |
| `packages/control-plane/src/routes/oauth/authorize.ts` | Modified | Uses shared PKCE, cached discovery, new validation |
| `packages/control-plane/src/routes/widget/connectors.ts` | Modified | Complete rewrite with all fixes |

## Related Documentation

| Document | Relevance |
|----------|-----------|
| [RFC 7636](https://datatracker.ietf.org/doc/html/rfc7636) | PKCE for OAuth Public Clients |
| [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) | OAuth 2.0 Authorization Server Metadata |
| [Cloudflare KV](https://developers.cloudflare.com/kv/api/) | TTL-based caching patterns |

## Prevention Strategies

### Code Duplication Prevention

- Search for function names across codebase before approving PRs
- Extract to `@maven/shared` when code is used in 2+ packages
- Cryptographic and validation utilities should always be shared

### Consistency Checks

- Document canonical patterns for each endpoint type
- Use shared middleware for cross-cutting concerns
- Maintain API style guide with concrete examples

### Security Hardening Checklist

- [ ] User input validated before use
- [ ] UUIDs and IDs validated with proper schemas
- [ ] Error messages don't leak sensitive information
- [ ] Redirect URIs validated with exact match
- [ ] Auth checks handle edge cases (empty strings, nulls)
- [ ] Rate limiting applied to sensitive endpoints

### Performance

- Cache external API calls with appropriate TTL
- Add timeouts to prevent hanging on slow servers
- OAuth discovery: 1-hour cache, 5-second timeout

## Code Review Checklist

Before approving OAuth-related PRs:

- [ ] No utility functions duplicated across packages
- [ ] All responses use defined types from `@maven/shared/types`
- [ ] Similar endpoints follow the same PKCE behavior
- [ ] External API calls are cached where appropriate
- [ ] Redirect URIs validated against allowlist
- [ ] Error messages don't expose internal details
- [ ] Path parameters validated before use
