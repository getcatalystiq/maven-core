---
title: Fix Chat Stream Response Buffering
type: fix
date: 2026-01-27
deepened: 2026-01-27
---

# Fix Chat Stream Response Buffering

## Enhancement Summary

**Deepened on:** 2026-01-27
**Research agents used:** kieran-typescript-reviewer, performance-oracle, architecture-strategist, code-simplicity-reviewer, pattern-recognition-specialist, best-practices-researcher, framework-docs-researcher, julik-frontend-races-reviewer, agent-native-reviewer

### Key Improvements
1. **Root cause identified**: Cloudflare compression (`Content-Encoding`) is the likely culprit, not `containerFetch`
2. **Critical missing header**: `Content-Encoding: identity` must be added to prevent compression buffering
3. **Race conditions identified**: Missing cancellation propagation and `cancel()` callback on ReadableStream
4. **Simplified investigation**: Single diagnostic test instead of three-phase approach

### New Considerations Discovered
- `containerFetch` does NOT buffer - it returns a streaming Response directly
- DO-to-Worker buffering is a known Cloudflare limitation (~1000 byte flush threshold)
- Browser `Accept-Encoding` headers trigger compression that breaks streaming
- Missing `cancel()` callback means client disconnects aren't propagated to SDK

---

## Overview

The chat stream endpoint (`/chat/stream`) returns responses all at once instead of progressively streaming. Users see the entire agent response appear suddenly rather than tokens appearing incrementally as they're generated.

## Problem Statement

When a user sends a chat message, the agent (running in a Cloudflare Sandbox container) properly creates a streaming NDJSON response via `ReadableStream`. However, by the time this response reaches the client widget, the entire response arrives at once rather than streaming progressively.

The bottleneck appears to be in how the Durable Object proxies the response from `containerFetch` back to the Tenant Worker and ultimately to the client.

### Research Insights: Root Cause Analysis

**Finding from framework-docs-researcher**: The `containerFetch` method does NOT buffer the response body. Examining `@cloudflare/containers` source code confirms it returns the Response directly from `tcpPort.fetch()` without consumption:

```typescript
// From @cloudflare/containers/dist/lib/container.js
async containerFetch(requestOrUrl, portOrInit, portParam) {
    // ... startup logic ...
    const res = await tcpPort.fetch(containerUrl, request);
    return res;  // <-- No buffering, returns Response as-is
}
```

**Finding from best-practices-researcher**: The ACTUAL cause is likely **Cloudflare's automatic compression**:

> "Cloudflare's automatic compression can break HTTP streaming. Setting `Content-Encoding: identity` explicitly disables compression and is essential for streaming to work with browser `fetch()`." - [Mintlify debugging article](https://www.mintlify.com/blog/debugging-a-mysterious-http-streaming-issue-when-cloudflare-compression-breaks-everything)

- **cURL** doesn't send `Accept-Encoding` headers → no compression → streaming works
- **Browsers** always send `Accept-Encoding: gzip, deflate, br` → compression enabled → response buffered

**Finding from performance-oracle**: Known Cloudflare limitation:

> "For anyone trying to use Stream API for long polling with Durable Objects: don't, responses are buffered and you can't control that." - [Cloudflare Community](https://community.cloudflare.com/t/durable-objects-response-streaming-doesnt-have-flushing-capabilities/330007)

The DO TransformStream reader flushes every ~1000 bytes. This is platform behavior, but `Content-Encoding: identity` may help bypass it.

---

## Investigation Findings

### Agent-Side Streaming (Working Correctly)

The agent at `packages/agent/src/routes/stream.ts:79-233` correctly:
- Creates a `ReadableStream` for the response
- Uses `safeEnqueue()` to push chunks incrementally
- Handles the `for await` loop from `sendMessage()` properly
- Emits NDJSON lines as events occur

### Research Insights: Agent Code Quality

**From kieran-typescript-reviewer:**
- The `safeEnqueue` pattern is correct but missing `cancel()` callback for client disconnects
- Session creation in `start()` delays first byte - consider pre-warming
- Type safety violation at line 159 with unsafe type narrowing

**From julik-frontend-races-reviewer:**
- **Critical**: `for await...of` loop continues after client disconnects, wasting API credits
- Missing `AbortSignal` propagation to `sendMessage()` generator
- No way to stop SDK session when client is gone

### Durable Object Proxy (Potential Bottleneck)

Location: `packages/tenant-worker/src/durable-objects/tenant-agent.ts:445-480`

```typescript
// Line 456: Awaits the full containerFetch response
const response = await this.sandbox.containerFetch(agentRequest, 8080);

// Lines 459-462: Error handling buffers entire body
if (!response.ok) {
  const errorText = await response.text(); // BUFFERS ENTIRE ERROR RESPONSE
  throw new Error(`Agent request failed: ${response.status} - ${errorText}`);
}

// Line 473: Returns response.body
return new Response(response.body, {
  headers: {
    'Content-Type': 'application/x-ndjson',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',
  },
});
```

### Research Insights: Missing Headers

**From best-practices-researcher and framework-docs-researcher:**

The current headers are incomplete. Add these critical headers:

```typescript
return new Response(response.body, {
  headers: {
    'Content-Type': 'application/x-ndjson',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',
    'Content-Encoding': 'identity',      // CRITICAL: Prevents compression buffering
    'Transfer-Encoding': 'chunked',      // Explicit chunked mode
  },
});
```

**From Hono docs:**
> "If you are developing an application for Cloudflare Workers, streaming may not work well on Wrangler without setting `Content-Encoding: Identity`"

### Research Insights: Inconsistent Patterns

**From pattern-recognition-specialist:**

The `proxyToAgent()` method (local dev) uses `TransformStream.pipeTo()`:
```typescript
const { readable, writable } = new TransformStream();
response.body.pipeTo(writable);  // Fire-and-forget, no error handling!
return new Response(readable, {...});
```

While `handleStreamChat()` (production) passes `response.body` directly. The direct pass-through is actually correct - the TransformStream in local dev is unnecessary overhead and has a bug (missing `.catch()` on `pipeTo()`).

---

## Simplified Investigation (Recommended)

**From code-simplicity-reviewer:** The three-phase investigation is over-engineered. Use a single diagnostic test:

### The Minimal Diagnostic

Add this to `tenant-agent.ts` temporarily:

```typescript
const response = await this.sandbox.containerFetch(agentRequest, 8080);
console.log(`[DIAG] containerFetch returned at T+${t()}ms`);

// Wrap body in TransformStream to log chunk arrival
const { readable, writable } = new TransformStream({
  transform(chunk, controller) {
    console.log(`[DIAG] Chunk received: ${chunk.length} bytes at T+${t()}ms`);
    controller.enqueue(chunk);
  }
});
response.body?.pipeTo(writable).catch(console.error);

return new Response(readable, {
  headers: {
    'Content-Type': 'application/x-ndjson',
    'Content-Encoding': 'identity',  // ADD THIS
    // ... rest of headers
  },
});
```

**Interpretation:**
- If chunks log incrementally but client sees delay → buffering is downstream (compression)
- If chunks log all at once → SDK or agent is buffering
- If chunks log incrementally AND client sees them → fix the headers, you're done

---

## Proposed Solution (Prioritized)

### Step 1: Add Missing Headers (Highest Confidence)

**Files:**
- `packages/tenant-worker/src/durable-objects/tenant-agent.ts:473-480`
- `packages/agent/src/routes/stream.ts:236-242`

```typescript
// In DO
return new Response(response.body, {
  headers: {
    'Content-Type': 'application/x-ndjson',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',
    'Content-Encoding': 'identity',      // ADD
    'Transfer-Encoding': 'chunked',      // ADD
  },
});

// In Agent
return new Response(stream, {
  headers: {
    'Content-Type': 'application/x-ndjson',
    'Cache-Control': 'no-cache',
    'Transfer-Encoding': 'chunked',
    'Content-Encoding': 'identity',      // ADD
  },
});
```

### Step 2: Fix Race Conditions (Important for Reliability)

**From julik-frontend-races-reviewer:**

Add `cancel()` callback and propagate abort signal:

```typescript
// In stream.ts
let abortController: AbortController;

const stream = new ReadableStream({
  async start(controller) {
    abortController = new AbortController();

    for await (const msg of sendMessage(session, message, abortController.signal)) {
      if (abortController.signal.aborted) break;
      safeEnqueue(encoder.encode(ndjsonLine(msg)));
    }
  },

  cancel(reason) {
    console.log(`[STREAM] Client disconnected:`, reason);
    abortController?.abort();
  }
});
```

Update `sendMessage` in `session-manager.ts` to accept and respect the signal:

```typescript
export async function* sendMessage(
  session: ManagedSession,
  message: string,
  signal?: AbortSignal
): AsyncGenerator<SDKMessage> {
  for await (const msg of session.sdkSession.stream()) {
    if (signal?.aborted) return;
    yield msg;
  }
}
```

### Step 3: Fix pipeTo Error Handling (Bug Fix)

**File:** `packages/tenant-worker/src/durable-objects/tenant-agent.ts:540-544`

```typescript
// Current (buggy)
response.body.pipeTo(writable);

// Fixed
response.body.pipeTo(writable).catch((error) => {
  console.error('Stream pipe failed:', error);
  try { writable.abort(error); } catch { /* already closed */ }
});
```

---

## What NOT to Do (Removed from Plan)

**From code-simplicity-reviewer:**

1. ~~Option C: WebSocket/SSE/Long-polling~~ - Premature. HTTP streaming should work with correct headers.
2. ~~Package version upgrades~~ - Current versions are fine. `containerFetch` doesn't buffer.
3. ~~Three-phase investigation~~ - Single diagnostic test is sufficient.
4. ~~proxyToSandbox() investigation~~ - It's for preview URLs, not relevant here.

---

## Acceptance Criteria

- [ ] Chat responses appear incrementally in the widget (tokens stream as generated)
- [ ] Time to first token (TTFT) is perceptibly fast (< 500ms after request)
- [ ] Full response matches what was expected (no truncation or data loss)
- [ ] Streaming works reliably across retry scenarios (sandbox wake-up, etc.)
- [ ] No regression in error handling behavior
- [ ] Client disconnect stops SDK processing (no wasted API credits)

### Research Insights: Testing Strategy

**From kieran-typescript-reviewer:**

```typescript
describe('streaming', () => {
  it('should emit chunks incrementally', async () => {
    const chunkTimes: number[] = [];
    const response = await fetch('/chat/stream', { ... });
    const reader = response.body!.getReader();

    while (true) {
      const { done, value } = await reader.read();
      chunkTimes.push(Date.now());
      if (done) break;
    }

    // Chunks should arrive spread out, not all at once
    const intervals = chunkTimes.slice(1).map((t, i) => t - chunkTimes[i]);
    expect(intervals.some(i => i > 100)).toBe(true);
  });
});
```

---

## Technical Considerations

### Cloudflare-Specific Constraints

- Durable Objects have different execution models than Workers
- containerFetch has documented limitations (no WebSocket support)
- **DO response streaming has ~1000 byte flush threshold** (platform limitation)
- **Compression must be disabled for streaming** via `Content-Encoding: identity`

### Research Insights: Hono Streaming

**From framework-docs-researcher:**

When using Hono streaming helpers on Cloudflare Workers:

```typescript
app.get('/stream', (c) => {
  c.header('Content-Encoding', 'Identity');  // CRITICAL for Wrangler
  return streamText(c, async (stream) => {
    await stream.writeln('Line 1');
  });
});
```

For pass-through (our case), return Response directly instead of using Hono's `c.body()`:

```typescript
// DON'T do this - may buffer:
return c.body(response.body);

// DO this - pass through directly:
return new Response(response.body, { headers: {...} });
```

### Current Response Headers

The DO sets these headers which should prevent buffering:
```typescript
'Cache-Control': 'no-cache, no-transform',
'Connection': 'keep-alive',
'X-Accel-Buffering': 'no',
```

**Missing (add these):**
```typescript
'Content-Encoding': 'identity',  // Prevents compression
'Transfer-Encoding': 'chunked',  // Explicit chunked mode
```

---

## Files to Modify

Primary:
- `packages/tenant-worker/src/durable-objects/tenant-agent.ts` - Add headers, fix pipeTo error handling
- `packages/agent/src/routes/stream.ts` - Add headers, add cancel() callback, propagate abort signal

Secondary:
- `packages/agent/src/session-manager.ts` - Accept AbortSignal in sendMessage()

---

## References

### Internal
- `packages/tenant-worker/src/durable-objects/tenant-agent.ts:445-480` - Current containerFetch handling
- `packages/agent/src/routes/stream.ts:79-233` - Agent streaming implementation
- `packages/agent/src/session-manager.ts:142-182` - sendMessage generator

### External
- [Cloudflare Sandbox SDK Docs](https://developers.cloudflare.com/sandbox/)
- [Cloudflare Workers Streams API](https://developers.cloudflare.com/workers/runtime-apis/streams/)
- [Container containerFetch API](https://github.com/cloudflare/containers)
- [Hono Streaming Helper](https://hono.dev/docs/helpers/streaming)
- [DO Streaming Flushing Limitations](https://community.cloudflare.com/t/durable-objects-response-streaming-doesnt-have-flushing-capabilities/330007)
- [Cloudflare Compression Breaking Streaming](https://www.mintlify.com/blog/debugging-a-mysterious-http-streaming-issue-when-cloudflare-compression-breaks-everything)

### Research Sources
- TypeScript review: kieran-typescript-reviewer agent
- Performance analysis: performance-oracle agent
- Architecture review: architecture-strategist agent
- Simplicity review: code-simplicity-reviewer agent
- Pattern analysis: pattern-recognition-specialist agent
- Best practices: best-practices-researcher agent
- Framework docs: framework-docs-researcher agent
- Race conditions: julik-frontend-races-reviewer agent
- Agent-native review: agent-native-reviewer agent
