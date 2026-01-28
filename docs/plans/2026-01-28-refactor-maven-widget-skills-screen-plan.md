---
title: Refactor Maven Widget Skills Screen to Use Maven Core APIs
type: refactor
date: 2026-01-28
deepened: 2026-01-28
---

# Refactor Maven Widget Skills Screen to Use Maven Core APIs

## Enhancement Summary

**Deepened on:** 2026-01-28
**Research agents used:** TypeScript Reviewer, Simplicity Reviewer, Architecture Strategist, Security Sentinel, Performance Oracle, Pattern Recognition, Agent-Native Reviewer, Frontend Races Reviewer, Best Practices Researcher, Framework Docs Researcher

### Key Improvements
1. **Use plain functions instead of class-based API client** - Simpler, ~50 LOC saved
2. **Add discriminated unions for state** - Prevents invalid state combinations
3. **Implement request ID tracking** - Prevents stale response bugs
4. **Use CodeMirror 6** - Smaller bundle (~200KB vs ~2MB Monaco)
5. **Make auto-assignment atomic** - Backend should handle in single transaction

### Critical Issues Identified
- Race conditions in skill selection and save operations
- Two-call create pattern creates orphan skills on partial failure
- Missing AbortController for request cancellation
- `hasUnsavedChanges` should be derived, not stored

---

## Overview

The maven-widget Skills screen currently uses a custom `skill-builder` API pattern with SSE responses and a proprietary operation-based protocol. This needs to be refactored to use the standard Maven Core `/admin/skills/*` REST endpoints and align with the new per-user skill access model.

## Problem Statement

### Current State (maven-widget)

The widget's skill management uses a custom SSE-based API:

```typescript
// Current pattern - all operations go through POST /tenants/{tenantId}/skill-builder
const response = await fetch(`${apiUrl}/tenants/${tenantId}/skill-builder`, {
  method: 'POST',
  body: JSON.stringify({
    operation: 'list_skills',  // or 'create_skill', 'update_skill', 'delete_skill'
    ...payload,
  }),
});
const data = await parseSSEResponse(response, 'skills');
```

**Problems:**
1. **Non-standard API pattern** - Uses SSE for CRUD operations instead of REST
2. **Type mismatch** - Widget's `SkillSummary` differs from core's `Skill` interface
3. **Missing features** - No support for:
   - Role-based skill access (`roles` field)
   - Per-user skill assignments
   - SKILL.md content editing (YAML frontmatter + prompt)
   - Enable/disable toggle
4. **Deprecated concepts** - Uses `slug`, `emoji`, `category`, `url_patterns`, `variables`, `draft_status` which don't exist in core
5. **No endpoint exists** - The `/tenants/{tenantId}/skill-builder` endpoint doesn't exist in maven-core

### Target State (Maven Core)

Maven Core provides standard REST endpoints at `/admin/skills/*`:

```typescript
// Target pattern - standard REST
GET    /admin/skills           // List skills
GET    /admin/skills/:id       // Get skill with content
POST   /admin/skills           // Create skill
PATCH  /admin/skills/:id       // Update skill
DELETE /admin/skills/:id       // Delete skill
POST   /admin/skills/:id/assign         // Assign to roles
POST   /admin/skills/:id/enable         // Enable skill
POST   /admin/skills/:id/disable        // Disable skill
GET    /admin/skills/:id/users          // List user assignments
POST   /admin/skills/:id/users/:userId  // Assign to user
DELETE /admin/skills/:id/users/:userId  // Remove from user
```

## Proposed Solution

Refactor the maven-widget Skills screen to:

1. Use standard REST API calls to `/admin/skills/*` endpoints
2. Align types with `@maven/shared` Skill interfaces
3. Remove deprecated concepts (slug, emoji, category, url_patterns, variables)
4. Add SKILL.md content editing and enable/disable toggle
5. Update the UI to reflect the new data model

**Important Simplification:**
- **Default behavior:** When creating a skill, it is automatically assigned to the current user only (no role/user management in this screen)
- **Edit modal:** Does NOT include role assignment or user assignment management - that's a separate admin concern
- The focus is on skill content management (name, description, SKILL.md), not access control

## Technical Approach

### Phase 1: Type Alignment

Update maven-widget types to match maven-core's `Skill` interface.

**File: `/src/skill-builder/types/index.ts`**

```typescript
// Import from shared package instead of duplicating
import type { Skill, SkillCreateRequest, SkillUpdateRequest } from '@maven/shared';

// Re-export for convenience
export type { Skill, SkillCreateRequest, SkillUpdateRequest };

// Widget-specific extension for content
export interface SkillWithContent extends Skill {
  readonly content: string;
}

// Structured error type for UI
export interface SkillsError {
  readonly message: string;
  readonly code?: string;
  readonly status?: number;
  readonly retryable: boolean;
}
```

#### Research Insights: Type Safety

**Best Practices:**
- Use `readonly` modifiers for API response types to prevent accidental mutation
- Import types from `@maven/shared` instead of duplicating definitions
- Use branded types for ISO date strings if additional type safety is needed

**Recommended Type Improvements:**
```typescript
// Branded type for ISO dates (optional, for extra safety)
type ISODateString = string & { readonly __brand: 'ISODateString' };

// Separate create/update payload types (don't reuse response types)
export interface SkillCreatePayload {
  name: string;
  description: string;
  content: string;
}

export interface SkillUpdatePayload {
  description?: string;
  content?: string;
}
```

---

### Phase 2: API Client Refactor

Replace the SSE-based `callApi` pattern with standard REST calls.

**File: `/src/skill-builder/api/skills.ts`** (NEW)

#### Research Insights: Simplicity

**Recommendation: Use plain functions instead of a class.** A class with constructor adds ceremony for what is just 5-6 fetch calls.

```typescript
// RECOMMENDED: Plain functions (~40 lines instead of 90)
import type { Skill, SkillWithContent, SkillCreatePayload, SkillUpdatePayload } from '../types';

type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ApiConfig {
  baseUrl: string;
  getToken: () => Promise<string>;
  userId: string;
}

let config: ApiConfig;

export function initSkillsApi(cfg: ApiConfig) {
  config = cfg;
}

async function request<T>(
  method: HttpMethod,
  path: string,
  body?: unknown,
  signal?: AbortSignal
): Promise<T> {
  const token = await config.getToken();

  const headers: HeadersInit = {
    'Authorization': `Bearer ${token}`,
  };

  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(`${config.baseUrl}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new ApiError(
      errorBody.message ?? `Request failed with status ${response.status}`,
      response.status,
      errorBody.code
    );
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// Public API - only the 6 operations actually used
export const listSkills = (signal?: AbortSignal) =>
  request<{ skills: Skill[]; total: number }>('GET', '/admin/skills', undefined, signal);

export const getSkill = (id: string, signal?: AbortSignal) =>
  request<SkillWithContent>('GET', `/admin/skills/${encodeURIComponent(id)}`, undefined, signal);

export const createSkillWithAssignment = async (
  data: SkillCreatePayload,
  signal?: AbortSignal
): Promise<Skill> => {
  const skill = await request<Skill>('POST', '/admin/skills', data, signal);
  // Auto-assign to current user
  await request('POST', `/admin/skills/${skill.id}/users/${config.userId}`, undefined, signal);
  return skill;
};

export const updateSkill = (id: string, data: SkillUpdatePayload, signal?: AbortSignal) =>
  request<Skill>('PATCH', `/admin/skills/${encodeURIComponent(id)}`, data, signal);

export const deleteSkill = (id: string, signal?: AbortSignal) =>
  request<void>('DELETE', `/admin/skills/${encodeURIComponent(id)}`, undefined, signal);

export const toggleSkillEnabled = (id: string, enabled: boolean, signal?: AbortSignal) =>
  request<void>('POST', `/admin/skills/${encodeURIComponent(id)}/${enabled ? 'enable' : 'disable'}`, undefined, signal);
```

#### Research Insights: API Client

**Best Practices:**
- Use `encodeURIComponent` for path parameters (security)
- Handle 204 No Content responses explicitly
- Include `AbortSignal` parameter for request cancellation
- Use structured `ApiError` class with status code

**Performance Considerations:**
- Implement request deduplication for concurrent identical requests
- Consider adding SWR-style caching for list/get operations

**Security Note:**
- Never accept `userId` from client - extract from JWT server-side
- The backend should validate that the user can only assign to themselves

---

### Phase 3: Context Refactor

Update `SkillBuilderContext.tsx` to use the new API client and simplified state.

**Key Changes:**

1. Remove file management state (files, selectedFile, openTabs, fileContents)
2. Remove chat state (chatSessionId, chatMessages) - not relevant to admin screen
3. Add skills content editing via SKILL.md
4. **No role/user assignment management** - skills are auto-assigned to current user on creation

#### Research Insights: State Management

**Critical: Use discriminated unions to prevent invalid states.**

```typescript
// RECOMMENDED: Discriminated unions for state machine
type SkillsListState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; error: SkillsError }
  | { status: 'loaded'; skills: readonly Skill[] };

type SelectedSkillState =
  | { status: 'none' }
  | { status: 'loading'; skillId: string }
  | { status: 'error'; skillId: string; error: SkillsError }
  | { status: 'loaded'; skill: SkillWithContent; draftContent: string };

type SaveState =
  | { status: 'idle' }
  | { status: 'saving'; contentAtSaveTime: string }
  | { status: 'error'; error: SkillsError };

export interface SkillsAdminState {
  readonly list: SkillsListState;
  readonly selected: SelectedSkillState;
  readonly save: SaveState;
}

// Derive hasUnsavedChanges - don't store it!
export function hasUnsavedChanges(state: SkillsAdminState): boolean {
  if (state.selected.status !== 'loaded') return false;
  return state.selected.draftContent !== state.selected.skill.content;
}
```

**Why discriminated unions?**
- TypeScript narrows types based on `status` field
- Impossible to have invalid state combinations (e.g., loading AND saving)
- Exhaustive switch statements catch missing cases
- Self-documenting state machine

#### Research Insights: Race Condition Prevention

**Critical: Track request IDs to prevent stale responses.**

```typescript
const loadRequestRef = useRef(0);

const selectSkill = useCallback(async (skillId: string) => {
  const thisRequest = ++loadRequestRef.current;

  dispatch({ type: 'SELECT_SKILL_START', skillId });

  try {
    const skill = await getSkill(skillId);

    // Stale response - user has moved on
    if (thisRequest !== loadRequestRef.current) {
      return;
    }

    dispatch({ type: 'SELECT_SKILL_SUCCESS', skill });
  } catch (error) {
    if (thisRequest !== loadRequestRef.current) return;
    dispatch({ type: 'SELECT_SKILL_ERROR', error: toSkillsError(error) });
  }
}, []);
```

**Save operation must capture content at save time:**

```typescript
const saveSkill = useCallback(async () => {
  if (state.selected.status !== 'loaded') return;

  const contentAtSaveTime = state.selected.draftContent;
  dispatch({ type: 'SAVE_START', contentAtSaveTime });

  try {
    await updateSkill(state.selected.skill.id, { content: contentAtSaveTime });

    // Only mark as saved if content hasn't changed during save
    dispatch({ type: 'SAVE_SUCCESS', contentAtSaveTime });
  } catch (error) {
    dispatch({ type: 'SAVE_ERROR', error: toSkillsError(error) });
  }
}, [state.selected]);
```

---

### Phase 4: UI Updates

**File: `/src/skill-builder/components/SkillsList.tsx`**

Update the skills list table to show core fields:

| Current Column | New Column | Notes |
|----------------|------------|-------|
| Name (with emoji) | Name | Remove emoji, keep name |
| Category | Description | Show description |
| URL Patterns | - | Remove |
| Variables | - | Remove |
| Actions | Actions + Toggle | Add enable/disable toggle |

**New Modal: Create/Edit Skill**

Replace the current form fields with a simplified form:

```typescript
interface SkillFormFields {
  name: string;           // Alphanumeric, underscores, hyphens (create only)
  description: string;    // Short description
  content: string;        // SKILL.md content (textarea or code editor)
}
```

**Note:** No role or user assignment fields in the edit modal. Skills are auto-assigned to the current user on creation.

#### Research Insights: Code Editor Choice

**Recommendation: Use CodeMirror 6 for widgets.**

| Factor | Monaco Editor | CodeMirror 6 | Winner |
|--------|--------------|--------------|--------|
| Bundle size | ~2-5MB | ~200KB | CodeMirror |
| Mobile support | Poor | Excellent | CodeMirror |
| Lazy loading | Difficult | Easy | CodeMirror |
| Best for | Full IDE | Lightweight | - |

**Implementation with lazy loading:**

```typescript
// /src/skill-builder/components/SkillEditor.tsx
import { lazy, Suspense } from 'react';

const CodeMirrorEditor = lazy(() => import('./CodeMirrorEditor'));

export function SkillEditor({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Suspense fallback={<div className="editor-skeleton">Loading editor...</div>}>
      <CodeMirrorEditor value={value} onChange={onChange} />
    </Suspense>
  );
}

// Preload on hover for perceived performance
export function preloadEditor() {
  import('./CodeMirrorEditor');
}
```

**CodeMirror setup for YAML/Markdown:**

```typescript
// /src/skill-builder/components/CodeMirrorEditor.tsx
import CodeMirror from '@uiw/react-codemirror';
import { markdown } from '@codemirror/lang-markdown';
import { yaml } from '@codemirror/lang-yaml';

export default function CodeMirrorEditor({ value, onChange }: Props) {
  return (
    <CodeMirror
      value={value}
      height="400px"
      extensions={[markdown(), yaml()]}
      onChange={onChange}
      theme="dark"
    />
  );
}
```

#### Research Insights: Toggle Race Condition

**Multiple rapid clicks on enable/disable toggle need handling:**

```typescript
const toggleRequestRef = useRef<Map<string, number>>(new Map());

const toggleSkillEnabled = useCallback(async (skillId: string, enabled: boolean) => {
  const requestId = (toggleRequestRef.current.get(skillId) ?? 0) + 1;
  toggleRequestRef.current.set(skillId, requestId);

  // Optimistic update
  dispatch({ type: 'SET_SKILL_ENABLED', skillId, enabled });

  try {
    await api.toggleSkillEnabled(skillId, enabled);

    if (toggleRequestRef.current.get(skillId) !== requestId) return;
  } catch (error) {
    // Rollback only if this is still the latest request
    if (toggleRequestRef.current.get(skillId) === requestId) {
      dispatch({ type: 'SET_SKILL_ENABLED', skillId, enabled: !enabled });
      dispatch({ type: 'SET_ERROR', error: toSkillsError(error) });
    }
  }
}, []);
```

---

### Phase 5: Remove Deprecated Code

**Files to Remove/Simplify:**

1. `/src/skill-builder/utils/sse.ts` - SSE parsing no longer needed
2. `/src/skill-builder/components/SkillFileBrowser.tsx` - File browsing not in core API
3. `/src/skill-builder/components/SkillCodeEditor.tsx` - Replace with SKILL.md editor
4. `/src/skill-builder/components/SkillChatPanel.tsx` - Chat not part of admin screen
5. `/src/skill-builder/components/SkillBuilderView.tsx` - Simplify to skill editor only

**Types to Remove from `SkillSummary`:**

- `slug` - Not in core
- `emoji` - Not in core
- `category` - Not in core
- `url_patterns` - Not in core
- `variables` - Not in core
- `draft_status` - Not in core

**API Methods NOT Exposed in Widget:**

The following API methods exist but are NOT used in the widget (admin-only concern):

- `assignToRoles()` - Role-based access management
- `listUserAssignments()` - View all users with access
- `assignToUser()` - Only used internally during skill creation
- `removeFromUser()` - User access management

---

## Research Insights: Architecture

### Widget Calling `/admin/*` Endpoints

**Concern:** The `/admin/*` namespace semantically implies full administrative access. A widget embedding in external sites should not conceptually be an "admin client."

**Recommendations:**
1. **Short-term:** Document that widget users must have `admin` role
2. **Long-term:** Consider a `/widget/skills/*` facade with appropriate semantics

### Two-Call Create Pattern Risk

**Issue:** Skill creates successfully, assignment fails → orphan skill exists but user can't see it.

**Recommendation:** Backend should handle auto-assignment atomically:

```typescript
// Backend: POST /admin/skills should accept autoAssign flag
POST /admin/skills
{
  "name": "my-skill",
  "content": "...",
  "autoAssign": true  // Explicitly request assignment to creator
}
```

If backend change not possible, handle partial success explicitly:

```typescript
async createSkillWithAssignment(data: SkillCreatePayload): Promise<Skill> {
  const skill = await request<Skill>('POST', '/admin/skills', data);

  try {
    await request('POST', `/admin/skills/${skill.id}/users/${config.userId}`);
  } catch (assignmentError) {
    throw new PartialCreateError(
      `Skill "${skill.name}" was created but couldn't be assigned. ` +
      `Contact support with skill ID: ${skill.id}`,
      { skillId: skill.id, originalError: assignmentError }
    );
  }

  return skill;
}
```

---

## Research Insights: Security

### JWT Handling

**Recommendations:**
- Use `sessionStorage` instead of `localStorage` (cleared on tab close)
- Implement token refresh before expiration (5-minute buffer)
- Never include tokens in URLs

### XSS Risks with SKILL.md Content

**Critical:** Users editing SKILL.md content that becomes agent instructions.

**Recommendations:**
- Sanitize markdown before rendering previews with DOMPurify
- Backend should validate content for dangerous patterns
- Consider a validation endpoint: `POST /admin/skills/validate`

### Input Validation

```typescript
const SKILL_NAME_REGEX = /^[a-zA-Z][a-zA-Z0-9_-]{2,49}$/;

function validateSkillName(name: string): { valid: boolean; error?: string } {
  if (!name || name.length < 3) {
    return { valid: false, error: 'Skill name must be at least 3 characters' };
  }
  if (name.length > 50) {
    return { valid: false, error: 'Skill name must be at most 50 characters' };
  }
  if (!SKILL_NAME_REGEX.test(name)) {
    return { valid: false, error: 'Skill name must start with a letter and contain only letters, numbers, hyphens, and underscores' };
  }
  const reserved = ['admin', 'system', 'default', 'null', 'undefined'];
  if (reserved.includes(name.toLowerCase())) {
    return { valid: false, error: 'This skill name is reserved' };
  }
  return { valid: true };
}
```

---

## Research Insights: Performance

### Caching Strategy

```typescript
class SkillsCache {
  private cache = new Map<string, { data: Skill; timestamp: number }>();
  private readonly TTL = 60_000; // 1 minute

  get(id: string): Skill | null {
    const cached = this.cache.get(id);
    if (!cached) return null;
    if (Date.now() - cached.timestamp > this.TTL) {
      this.cache.delete(id);
      return null;
    }
    return cached.data;
  }

  set(id: string, data: Skill) {
    this.cache.set(id, { data, timestamp: Date.now() });
  }

  invalidate(id: string) {
    this.cache.delete(id);
  }
}
```

### Bundle Size

| Component | Before | After | Savings |
|-----------|--------|-------|---------|
| Editor | ~2MB (Monaco) | ~200KB (CodeMirror) | ~1.8MB |
| SSE Utils | ~5KB | 0 | ~5KB |
| Unused methods | ~2KB | 0 | ~2KB |

---

## Acceptance Criteria

### Functional Requirements

- [x] Skills list fetches from `GET /admin/skills` endpoint
- [x] Create skill uses `POST /admin/skills` with name, description, content (no roles)
- [x] Created skill is auto-assigned to current user via `POST /admin/skills/:id/users/:userId`
- [x] Edit skill uses `PATCH /admin/skills/:id` with description and content only
- [x] Delete skill uses `DELETE /admin/skills/:id`
- [x] Enable/disable skill uses `POST /admin/skills/:id/enable|disable`
- [x] View skill content loads SKILL.md via `GET /admin/skills/:id`

### Non-Functional Requirements

- [x] Types align with `@maven/shared` interfaces
- [x] No SSE parsing - standard JSON responses
- [x] Error handling for all API failures
- [x] Loading states for async operations
- [x] Form validation for skill name (alphanumeric, underscore, hyphen only)
- [x] Request cancellation on component unmount (AbortController)
- [x] Race condition prevention with request ID tracking

### Migration Requirements

- [x] Existing code that depends on deprecated fields (emoji, slug, etc.) is updated
- [x] SSE utilities are removed if no longer used elsewhere
- [x] Context provider interface remains backward compatible OR all consumers updated

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `src/skill-builder/types/index.ts` | MODIFY | Import from @maven/shared, add discriminated unions |
| `src/skill-builder/api/skills.ts` | CREATE | New REST API client (plain functions) |
| `src/skill-builder/context/SkillBuilderContext.tsx` | MODIFY | Use new API, discriminated union state |
| `src/skill-builder/components/SkillsList.tsx` | MODIFY | Update columns, add toggle handling |
| `src/skill-builder/components/SkillEditor.tsx` | CREATE | CodeMirror-based SKILL.md editor |
| `src/skill-builder/components/CodeMirrorEditor.tsx` | CREATE | Lazy-loaded CodeMirror wrapper |
| `src/skill-builder/components/SkillFileBrowser.tsx` | DELETE | Not needed |
| `src/skill-builder/components/SkillCodeEditor.tsx` | DELETE | Replace with SkillEditor |
| `src/skill-builder/components/SkillChatPanel.tsx` | DELETE | Not part of admin |
| `src/skill-builder/components/SkillBuilderView.tsx` | MODIFY | Simplify to skill editing |
| `src/skill-builder/utils/sse.ts` | DELETE | No longer needed |
| `src/types.ts` | MODIFY | Update Skill interface |

---

## Dependencies & Risks

### Dependencies

1. **Maven Core API availability** - Widget must point to deployed control-plane
2. **Authentication** - Widget must have valid admin JWT token
3. **Tenant context** - API routes require tenant ID from token
4. **CodeMirror packages** - `@uiw/react-codemirror`, `@codemirror/lang-yaml`, `@codemirror/lang-markdown`

### Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Breaking change for existing widgets | High | Version bump, migration guide |
| Two-call create creates orphan skills | Medium | Backend atomic operation (preferred) or explicit error handling |
| Race conditions on rapid interactions | Medium | Request ID tracking, optimistic UI with rollback |
| XSS via SKILL.md content | Medium | DOMPurify sanitization, backend validation |
| Bundle size regression | Low | Lazy load editor, verify with bundle analyzer |

---

## References

### Maven Core Files

- Type definitions: `packages/shared/src/types/skill.ts`
- Admin routes: `packages/control-plane/src/routes/admin/skills.ts`
- Services: `packages/control-plane/src/services/skills.ts`
- Validation: `packages/shared/src/validation/schemas.ts`

### Maven Widget Files

- Current types: `src/skill-builder/types/index.ts`
- Current context: `src/skill-builder/context/SkillBuilderContext.tsx`
- Skills list: `src/skill-builder/components/SkillsList.tsx`

### Related Plans

- Native SDK skill loading: `docs/plans/2026-01-27-feat-native-sdk-skill-loading-plan.md`

### External References

- [React 19 Hooks Documentation](https://react.dev/reference/react)
- [TypeScript 5.x Release Notes](https://www.typescriptlang.org/docs/handbook/release-notes/)
- [CodeMirror 6 Documentation](https://codemirror.net/)
- [AbortController MDN Reference](https://developer.mozilla.org/en-US/docs/Web/API/AbortController)
