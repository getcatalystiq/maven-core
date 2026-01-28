---
status: complete
priority: p2
issue_id: "002"
tags: [code-review, security, oauth]
dependencies: ["001"]
---

# PKCE Behavioral Inconsistency Between Endpoints

## Problem Statement

The two OAuth initiation paths have different PKCE enforcement behavior:

**Widget endpoint** (`packages/control-plane/src/routes/widget/connectors.ts:164-166`):
```typescript
// Generate PKCE (always use S256 per RFC 9700)
const codeVerifier = generateCodeVerifier();
const codeChallenge = await generateCodeChallenge(codeVerifier);
```
- Always adds PKCE unconditionally

**OAuth authorize endpoint** (`packages/control-plane/src/routes/oauth/authorize.ts:129-135`):
```typescript
if (oauthMetadata.code_challenge_methods_supported?.includes('S256')) {
  codeVerifier = generateCodeVerifier();
  // ...
}
```
- Only adds PKCE if server advertises support

**Why this matters:**
- Inconsistent security posture between endpoints
- Widget flows could fail with MCP servers that don't support PKCE
- Confusing for developers debugging OAuth issues

## Findings

**From security-sentinel agent:**
- Severity: LOW (more of a reliability issue)
- "Inconsistent PKCE enforcement creates inconsistent security postures"

**From pattern-recognition-specialist agent:**
- "This could cause OAuth failures with servers that do not support PKCE"

**From code-simplicity-reviewer agent:**
- "Inconsistency adds confusion without clear justification"

## Proposed Solutions

### Solution A: Always require PKCE (Recommended for security)

Make both endpoints always use PKCE. Modern OAuth providers should support S256.

**Pros:** Stronger security, consistent behavior
**Cons:** May break with legacy OAuth servers
**Effort:** Small
**Risk:** Medium (potential breaking change)

### Solution B: Check server support in both endpoints

Make widget endpoint also check `oauthMetadata.code_challenge_methods_supported`.

**Pros:** Consistent with existing authorize endpoint, maximum compatibility
**Cons:** Weaker security stance
**Effort:** Small
**Risk:** Low

### Solution C: Document the difference

Keep current behavior but document why widget always requires PKCE.

**Pros:** No code changes
**Cons:** Doesn't address the inconsistency
**Effort:** Minimal
**Risk:** Low

## Recommended Action

<!-- Filled during triage -->

## Technical Details

**Affected files:**
- `packages/control-plane/src/routes/widget/connectors.ts`
- `packages/control-plane/src/routes/oauth/authorize.ts`

**Components:** OAuth flow initiation

## Acceptance Criteria

- [ ] Both OAuth initiation paths have consistent PKCE behavior
- [ ] Decision documented (either always require or always check support)
- [ ] OAuth flows work with test MCP servers

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-28 | Created during code review | Both approaches have trade-offs |

## Resources

- RFC 7636: PKCE for OAuth
- RFC 9700: OAuth 2.0 Best Current Practice (recommends PKCE)
