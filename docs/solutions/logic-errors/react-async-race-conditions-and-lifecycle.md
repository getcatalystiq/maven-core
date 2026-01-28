---
title: React async state management with shared AbortController and stale closures
category: logic-errors
tags:
  - react
  - useReducer
  - abort-controller
  - stale-closure
  - memory-leak
  - optimistic-updates
  - async-state
  - unmounted-component
  - race-condition
module: maven-widget/SkillsScreen
symptoms:
  - API requests cancelled unexpectedly when switching between operations
  - React warnings about state updates on unmounted components
  - Deleted skills not properly deselected due to stale closure
  - Memory leak from toggle request tracking Map
  - Unused props in component interface
root_cause: Shared AbortController instance caused mutual cancellation between independent async operations; missing mount guards allowed state updates after unmount; closure captured stale state reference instead of using reducer for current state access
date_documented: 2026-01-28
---

# React Async Race Conditions and Lifecycle Issues

## Problem Statement

A React context managing async operations (loading skills, selecting skills, saving, toggling) had multiple race condition and lifecycle issues that caused unpredictable behavior:

1. **Mutual cancellation** - A single `AbortController` was shared across different operation types, causing unrelated operations to cancel each other
2. **Unmounted component updates** - Async callbacks attempted state updates after component unmount
3. **Stale closures** - Callbacks captured state values that became outdated by the time async operations completed
4. **Memory leaks** - Map entries tracking request IDs were never cleaned up when skills were deleted

## Solution

### Fix 1: Separate AbortControllers per Operation Type

**Key Insight:** Each independent operation type needs its own AbortController so operations don't accidentally cancel each other.

**Before:**
```typescript
const abortControllerRef = useRef<AbortController | null>(null);

// In loadSkills:
abortControllerRef.current?.abort();  // Cancels selectSkill!

// In selectSkill:
abortControllerRef.current?.abort();  // Cancels loadSkills!
```

**After:**
```typescript
const loadSkillsAbortRef = useRef<AbortController | null>(null);
const selectSkillAbortRef = useRef<AbortController | null>(null);

// In loadSkills - only aborts previous loadSkills call
loadSkillsAbortRef.current?.abort();
loadSkillsAbortRef.current = new AbortController();

// In selectSkill - only aborts previous selectSkill call
selectSkillAbortRef.current?.abort();
selectSkillAbortRef.current = new AbortController();
```

### Fix 2: Mount Guards for Async Callbacks

**Key Insight:** Always check if the component is still mounted before updating state in async callbacks to prevent "setState on unmounted component" errors.

**Implementation:**
```typescript
const isMountedRef = useRef(true);

useEffect(() => {
  isMountedRef.current = true;
  return () => {
    isMountedRef.current = false;
    // Clean up all pending requests on unmount
    loadSkillsAbortRef.current?.abort();
    selectSkillAbortRef.current?.abort();
  };
}, []);

// In every async callback, guard state updates:
const loadSkills = useCallback(async () => {
  try {
    const skills = await fetchSkills(signal);

    // Guard: Don't update state if unmounted
    if (!isMountedRef.current) return;

    dispatch({ type: 'LOAD_SUCCESS', skills });
  } catch (error) {
    if (!isMountedRef.current) return;
    dispatch({ type: 'LOAD_ERROR', error });
  }
}, []);
```

### Fix 3: Avoid Stale Closures with Reducer Actions

**Key Insight:** Instead of reading state in callbacks (which captures a stale snapshot), dispatch actions that let the reducer check current state.

**Before (stale closure problem):**
```typescript
const deleteSkillFn = useCallback(async (skillId: string) => {
  await apiDeleteSkill(skillId);
  // BUG: state.selected was captured when callback was created
  // It may be stale by the time the await completes!
  if (state.selected.status === 'loaded' && state.selected.skill.id === skillId) {
    dispatch({ type: 'DESELECT_SKILL' });
  }
}, [state.selected]);  // Re-creates on every state.selected change - expensive!
```

**After (reducer handles state check):**
```typescript
// Add new action type to the reducer
type Action =
  | { type: 'DESELECT_IF_SELECTED'; skillId: string }
  // ... other actions

// Reducer checks current state at dispatch time
function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'DESELECT_IF_SELECTED':
      // State is current here, not stale!
      if (state.selected.status === 'loaded' &&
          state.selected.skill.id === action.skillId) {
        return { ...state, selected: { status: 'none' }, save: { status: 'idle' } };
      }
      return state;
    // ...
  }
}

// Callback is simple with no state dependencies
const deleteSkillFn = useCallback(async (skillId: string) => {
  await apiDeleteSkill(skillId);
  // Let the reducer check current state
  dispatch({ type: 'DESELECT_IF_SELECTED', skillId });
}, []);  // Empty deps - never recreated!
```

### Fix 4: Clean Up Map Entries to Prevent Memory Leaks

**Key Insight:** When tracking per-entity state in Maps or objects, remove entries when entities are deleted.

**Before (memory leak):**
```typescript
// Map grows forever as skills are created/deleted
const toggleRequestRef = useRef(new Map<string, number>());

const deleteSkillFn = useCallback(async (skillId: string) => {
  await apiDeleteSkill(skillId);
  // Entry for deleted skill stays in the Map forever!
}, []);
```

**After (cleanup on delete):**
```typescript
const toggleRequestRef = useRef(new Map<string, number>());

const deleteSkillFn = useCallback(async (skillId: string) => {
  await apiDeleteSkill(skillId);
  // Clean up tracking data for deleted skill
  toggleRequestRef.current.delete(skillId);
  dispatch({ type: 'DESELECT_IF_SELECTED', skillId });
}, []);
```

### Summary Table

| Issue | Root Cause | Solution |
|-------|------------|----------|
| Mutual cancellation | Shared AbortController | Separate refs per operation type |
| Unmounted updates | No lifecycle awareness | `isMountedRef` guard in all async callbacks |
| Stale closures | State captured at callback creation | Move state checks into reducer actions |
| Memory leak | Map entries never deleted | Clean up on entity deletion |

## Prevention

### Code Review Checklist

- [ ] **AbortController Isolation**: Each independent async operation type has its own AbortController or request ID tracking mechanism
- [ ] **Mount Guard Pattern**: All async callbacks check component mount status before dispatching state updates
- [ ] **Stale Closure Prevention**: `useCallback` dependencies are minimal; state checks and validations are moved to reducers where they always see current state
- [ ] **Tracking Ref Cleanup**: Refs that track per-entity data clean up entries when entities are deleted
- [ ] **Request ID Tracking**: Long-running operations use incrementing request IDs to detect and ignore stale responses
- [ ] **Optimistic Update Rollback**: Optimistic UI updates include rollback logic that only executes if the request is still the latest for that entity

### Patterns to Adopt

1. **One AbortController/Request ID per operation type**
   ```typescript
   // GOOD: Separate tracking per operation type
   const loadRequestRef = useRef(0);
   const toggleRequestRef = useRef<Map<string, number>>(new Map());

   // BAD: Single shared controller
   const abortControllerRef = useRef(new AbortController());
   ```

2. **Mount guard pattern with request ID comparison**
   ```typescript
   const selectSkill = useCallback(async (skillId: string) => {
     const thisRequest = ++loadRequestRef.current;
     dispatch({ type: 'SELECT_SKILL_START', skillId });

     try {
       const skill = await getSkill(skillId);
       if (thisRequest !== loadRequestRef.current) return;
       dispatch({ type: 'SELECT_SKILL_SUCCESS', skill });
     } catch (error) {
       if (thisRequest !== loadRequestRef.current) return;
       dispatch({ type: 'SELECT_SKILL_ERROR', error });
     }
   }, []);
   ```

3. **Move state checks to reducers** - Reducers always see current state; callbacks may have stale snapshots

4. **Explicit cleanup in delete operations** - Always clean tracking refs when entities are removed

5. **Capture values at operation start time** - Pass captured values to reducer for comparison

### Anti-Patterns to Avoid

1. **Sharing AbortController across unrelated operations** - Each operation type needs independent cancellation
2. **Trusting useCallback dependencies to keep closures fresh** - State captured at callback creation becomes stale during async execution
3. **Assuming Maps/Sets in refs self-clean** - They persist across renders but never shrink without explicit deletion
4. **Optimistic updates without request ID validation** - Track request IDs per entity for optimistic updates
5. **Derived state stored in state** - `hasUnsavedChanges` should be computed, not stored

### Test Ideas

**Unit Tests for Reducer Logic:**
```typescript
describe('skillsReducer', () => {
  it('SAVE_SUCCESS only clears dirty flag when content matches', () => {
    const state = {
      selected: { status: 'loaded', skill: mockSkill, draftContent: 'new content' },
      save: { status: 'saving', contentAtSaveTime: 'old content' }
    };

    const result = reducer(state, { type: 'SAVE_SUCCESS', contentAtSaveTime: 'old content' });
    expect(hasUnsavedChanges(result)).toBe(true);
  });
});
```

**Integration Tests for Race Conditions:**
```typescript
describe('race condition handling', () => {
  it('ignores stale skill detail responses', async () => {
    const { result } = renderHook(() => useSkillsContext());

    act(() => result.current.selectSkill('skill-a'));
    act(() => result.current.selectSkill('skill-b')); // Before A completes

    await resolveSkillRequest('skill-a'); // Stale
    expect(result.current.state.selected.skillId).toBe('skill-b');
  });
});
```

## Related Documentation

### Internal References

- [Maven Widget Skills Screen Refactor Plan](../../plans/2026-01-28-refactor-maven-widget-skills-screen-plan.md) - Source of these patterns
- [Chat Stream Response Buffering Fix](../../plans/2026-01-27-fix-chat-stream-response-buffering-plan.md) - Related AbortController patterns for streaming

### External References

- [MDN AbortController Reference](https://developer.mozilla.org/en-US/docs/Web/API/AbortController)
- [React useCallback Documentation](https://react.dev/reference/react/useCallback)
- [React useEffect Cleanup](https://react.dev/learn/synchronizing-with-effects#step-3-add-cleanup-if-needed)

## Files Changed

| File | Changes |
|------|---------|
| `src/skill-builder/context/SkillBuilderContext.tsx` | Separate AbortControllers, mount guards, new reducer action |
| `src/skill-builder/types/index.ts` | Added `DESELECT_IF_SELECTED` action type |
| `src/skill-builder/components/SkillsList.tsx` | Removed unused `onClose` prop |
| `src/skill-builder/components/SkillBuilderView.tsx` | Updated prop passing |
