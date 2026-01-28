---
status: complete
priority: p2
issue_id: "001"
tags: [code-review, architecture, dry]
dependencies: []
---

# PKCE Code Duplication

## Problem Statement

Three PKCE helper functions (`generateCodeVerifier`, `generateCodeChallenge`, `base64UrlEncode`) are duplicated verbatim between two files:
- `packages/control-plane/src/routes/oauth/authorize.ts` (lines 37-62)
- `packages/control-plane/src/routes/widget/connectors.ts` (lines 30-55)

This is 29 lines of identical cryptographic utility code that should be shared.

**Why this matters:**
- DRY violation increases maintenance burden
- Risk of behavioral divergence if one copy is modified
- These are security-critical functions that should have single source of truth

## Findings

**From pattern-recognition-specialist agent:**
- Functions are "byte-for-byte identical"
- Not exported from `@maven/shared` where crypto utilities normally reside
- `packages/shared/src/crypto/index.ts` already exports `jwt`, `password`, and `secrets` modules - PKCE would fit naturally

**From architecture-strategist agent:**
- Technical debt risk: "The duplicated PKCE functions will diverge over time"
- Recommended location: `@maven/shared/crypto`

**From code-simplicity-reviewer agent:**
- Estimated 29 LOC reduction if shared
- Most clear over-engineering in the implementation

## Proposed Solutions

### Solution A: Extract to @maven/shared/crypto (Recommended)

Create new file `packages/shared/src/crypto/pkce.ts`:
```typescript
export function generateCodeVerifier(): string { ... }
export async function generateCodeChallenge(verifier: string): Promise<string> { ... }
export function base64UrlEncode(buffer: Uint8Array): string { ... }
```

Export from `packages/shared/src/crypto/index.ts`.

**Pros:** Single source of truth, follows existing patterns, reusable across packages
**Cons:** Minor - requires shared package rebuild
**Effort:** Small (< 1 hour)
**Risk:** Low

### Solution B: Extract to control-plane utility

Create `packages/control-plane/src/utils/pkce.ts` and import in both route files.

**Pros:** No shared package change needed
**Cons:** Not reusable if tenant-worker ever needs PKCE
**Effort:** Small
**Risk:** Low

## Recommended Action

<!-- Filled during triage -->

## Technical Details

**Affected files:**
- `packages/control-plane/src/routes/oauth/authorize.ts`
- `packages/control-plane/src/routes/widget/connectors.ts`
- `packages/shared/src/crypto/index.ts` (if Solution A)

**Components:** OAuth flow, Widget OAuth initiation

## Acceptance Criteria

- [ ] PKCE functions exist in single location
- [ ] Both `authorize.ts` and `widget/connectors.ts` import from shared location
- [ ] Types pass
- [ ] Existing OAuth flows still work

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-28 | Created during code review | Identified via parallel agent analysis |

## Resources

- PR: Current implementation (uncommitted changes)
- Related: `packages/shared/src/crypto/` for existing crypto utilities
