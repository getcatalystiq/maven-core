---
status: complete
priority: p3
issue_id: "008"
tags: [code-review, security, validation]
dependencies: []
---

# Missing ConnectorId UUID Validation in Path Parameter

## Problem Statement

The `connectorId` path parameter is used directly without format validation:

```typescript
// packages/control-plane/src/routes/widget/connectors.ts:123, 215
const connectorId = c.req.param('connectorId');
```

**Why this matters:**
- While database queries will fail for invalid IDs, unsanitized input in KV key construction could cause issues
- KV key: `connector:${tenantId}:${userId}:${connectorId}` - special characters could pollute keys
- Defense in depth: validate early, fail fast

## Findings

**From security-sentinel agent:**
- Severity: LOW
- "KV key injection if special characters are not handled"
- "Potential future injection vulnerabilities"
- Current risk is low due to database constraints

## Proposed Solutions

### Solution A: Add UUID validation (Recommended)

Validate connectorId matches UUID format before use:

```typescript
import { z } from 'zod';

const uuidParam = z.string().uuid();

app.post('/:connectorId/oauth/initiate', async (c) => {
  const connectorId = c.req.param('connectorId');
  const parsed = uuidParam.safeParse(connectorId);
  if (!parsed.success) {
    throw new HTTPException(400, { message: 'Invalid connector ID format' });
  }
  // ...
});
```

Or use path parameter validation middleware.

**Pros:** Defense in depth, fast failure, prevents KV key issues
**Cons:** Minor additional validation overhead
**Effort:** Small
**Risk:** None

### Solution B: Accept current behavior

Database constraint and "not found" response handle invalid IDs.

**Pros:** No code changes
**Cons:** Relies on downstream validation
**Effort:** None
**Risk:** Low (current)

## Recommended Action

<!-- Filled during triage -->

## Technical Details

**Affected files:**
- `packages/control-plane/src/routes/widget/connectors.ts`
- Similar pattern in admin routes

## Acceptance Criteria

- [ ] Invalid UUID in path returns 400 (not 404 or 500)
- [ ] Valid UUIDs work unchanged
- [ ] KV keys cannot be polluted

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-28 | Created during code review | Defense in depth improvement |

## Resources

- `packages/shared/src/validation/schemas.ts` has `uuidSchema` already
