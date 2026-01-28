---
status: complete
priority: p3
issue_id: "006"
tags: [code-review, security, edge-case]
dependencies: []
---

# Empty TenantId Handling for Super-Admins

## Problem Statement

The JWT auth middleware sets `tenantId` to empty string for super-admins:

```typescript
// packages/control-plane/src/middleware/auth.ts:35
c.set('tenantId', payload.tenant_id ?? '');
```

Widget routes then use this empty string in database queries and KV keys:

```typescript
const connectors = await listEnabledConnectors(c.env.DB, tenantId); // tenantId = ''
const token = await getConnectorToken(c.env.KV, tenantId, userId, connector.id);
// Key becomes: connector::userId:connectorId
```

**Why this matters:**
- Super-admins calling widget endpoints get unexpected empty results
- KV keys with empty tenant segment could cause key collision issues
- No explicit guard against this edge case

## Findings

**From security-sentinel agent:**
- Severity: MEDIUM
- "Data isolation issues, potential cross-tenant token access"
- Exploitability: Low (super-admins are trusted)

**From architecture-strategist agent:**
- "Widget routes assume a valid tenantId exists but do not guard against this edge case"

## Proposed Solutions

### Solution A: Require tenantId for widget routes (Recommended)

Add validation at the start of widget route handlers:

```typescript
app.use('/', async (c, next) => {
  const tenantId = c.get('tenantId');
  if (!tenantId) {
    throw new HTTPException(400, {
      message: 'Tenant context required. Super-admins must specify X-Tenant-Id header.'
    });
  }
  await next();
});
```

**Pros:** Clear error message, prevents unexpected behavior
**Cons:** Super-admins must explicitly specify tenant
**Effort:** Small
**Risk:** Low

### Solution B: Allow super-admin tenant override in widget routes

Check for `X-Tenant-Id` header in widget routes like admin routes do:

```typescript
if (isSuperAdmin) {
  const overrideTenant = c.req.query('tenantId') || c.req.header('X-Tenant-Id');
  if (overrideTenant) {
    c.set('tenantId', overrideTenant);
  }
}
```

**Pros:** Consistent with admin routes
**Cons:** Widget routes would need adminAuth-like logic
**Effort:** Medium
**Risk:** Low

## Recommended Action

<!-- Filled during triage -->

## Technical Details

**Affected files:**
- `packages/control-plane/src/routes/widget/connectors.ts`
- `packages/control-plane/src/middleware/auth.ts`

## Acceptance Criteria

- [ ] Super-admin users get clear error when calling widget routes without tenant context
- [ ] Or super-admin override mechanism works for widget routes
- [ ] Normal users (with tenant_id in JWT) are unaffected

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-28 | Created during code review | Edge case for super-admin API usage |

## Resources

- Existing admin route super-admin handling: `packages/control-plane/src/middleware/auth.ts:64-70`
