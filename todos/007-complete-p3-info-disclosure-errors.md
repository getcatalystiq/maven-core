---
status: complete
priority: p3
issue_id: "007"
tags: [code-review, security, error-handling]
dependencies: []
---

# Information Disclosure in Error Messages

## Problem Statement

Error messages reveal internal implementation details:

```typescript
// packages/control-plane/src/routes/widget/connectors.ts:159-162
throw new HTTPException(400, {
  message: `MCP server does not support OAuth discovery at ${mcpServerUrl}`,
});
```

**Why this matters:**
- Exposes internal MCP server URLs to clients
- Information gathering opportunity for attackers
- Leaks infrastructure details

## Findings

**From security-sentinel agent:**
- Severity: LOW
- "Exposing the MCP server URL in error messages can leak internal infrastructure details"

## Proposed Solutions

### Solution A: Generic error messages (Recommended)

Return generic messages to clients, log details server-side:

```typescript
console.error(`OAuth discovery failed for connector ${connectorId} at ${mcpServerUrl}`);
throw new HTTPException(400, {
  message: 'Connector does not support OAuth authentication',
});
```

**Pros:** No information leakage, maintains debuggability via logs
**Cons:** Less helpful error messages for legitimate debugging
**Effort:** Small
**Risk:** None

### Solution B: Environment-based verbosity

Show detailed errors only in development:

```typescript
const message = c.env.ENVIRONMENT === 'development'
  ? `MCP server does not support OAuth discovery at ${mcpServerUrl}`
  : 'Connector does not support OAuth authentication';
```

**Pros:** Helpful in dev, secure in prod
**Cons:** Requires environment configuration
**Effort:** Small
**Risk:** Low

## Recommended Action

<!-- Filled during triage -->

## Technical Details

**Affected files:**
- `packages/control-plane/src/routes/widget/connectors.ts`
- Similar pattern in other error handlers

## Acceptance Criteria

- [ ] Production error messages don't expose internal URLs
- [ ] Errors still logged for debugging
- [ ] Development remains debuggable

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-28 | Created during code review | Minor information disclosure |

## Resources

- OWASP: Error Handling guidance
