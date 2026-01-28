---
status: complete
priority: p2
issue_id: "003"
tags: [code-review, typescript, quality]
dependencies: []
---

# Missing Typed Responses in Widget Routes

## Problem Statement

The widget routes define response types in `@maven/shared` but don't use them for all endpoints:

**Defined types not used:**
- `OAuthInitiateResponse` (`packages/shared/src/types/widget.ts:29-31`)
- `DisconnectResponse` (`packages/shared/src/types/widget.ts:36-38`)

**Current code returns inline objects:**
```typescript
// Line 204 - should use OAuthInitiateResponse
return c.json({ authorizationUrl });

// Line 235 - should use DisconnectResponse
return c.json({ disconnected: true });
```

**Why this matters:**
- Types exist but aren't used, reducing type safety
- Response shapes could drift from documented types
- Less IDE support for consumers of these endpoints

## Findings

**From pattern-recognition-specialist agent:**
- "Uses explicit response types from shared" for list endpoint (correct)
- "Missing typed responses" for initiate and disconnect endpoints

## Proposed Solutions

### Solution A: Use the existing types (Recommended)

Import and use `OAuthInitiateResponse` and `DisconnectResponse`:

```typescript
import type { OAuthInitiateResponse, DisconnectResponse } from '@maven/shared';

// Line 204
const response: OAuthInitiateResponse = { authorizationUrl };
return c.json(response);

// Line 235
const response: DisconnectResponse = { disconnected: true };
return c.json(response);
```

**Pros:** Full type safety, consistent with list endpoint
**Cons:** Minor verbosity
**Effort:** Small (< 15 minutes)
**Risk:** None

### Solution B: Remove the unused types

If the types add no value, remove them from `widget.ts`.

**Pros:** Less code to maintain
**Cons:** Loses documentation value of types
**Effort:** Small
**Risk:** Low

## Recommended Action

<!-- Filled during triage -->

## Technical Details

**Affected files:**
- `packages/control-plane/src/routes/widget/connectors.ts`
- `packages/shared/src/types/widget.ts` (if removing types)

## Acceptance Criteria

- [ ] All widget endpoint responses use typed objects OR
- [ ] Unused types removed from shared package
- [ ] Types pass

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-28 | Created during code review | Types defined but not used |

## Resources

- `packages/shared/src/types/widget.ts`
