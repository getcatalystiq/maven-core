---
title: "fix: Durable Object WebSocket Stability"
type: fix
date: 2026-01-26
reviewed: 2026-01-27
---

# fix: Durable Object WebSocket Stability

## Review Summary

**Reviewed by:** DHH Rails Reviewer, Kieran TypeScript Reviewer, Code Simplicity Reviewer
**Verdict:** Radically simplify. The original plan was over-engineered.

### Key Decisions

1. **Delete circuit breaker** - "cargo cult engineering" for a single DO-sandbox connection
2. **Delete mutex** - DO is single-threaded, mutex adds complexity without benefit
3. **Delete connection limits** - Move to edge/worker layer if needed, not DO
4. **Delete jitter** - Solving Netflix's problems, not ours
5. **Delete structured error responses** - No client uses these fields today
6. **Keep retry loop** - Simple, effective, ~20 lines
7. **Keep SIGTERM handler** - Required for graceful shutdown, ~15 lines

**Total fix: ~35 lines of code**

---

## Overview

The TenantAgent Durable Object WebSocket implementation hangs regularly and is unstable. Root causes:

1. **No retry logic** for `wsConnect()` failures
2. **State desync** - `agentProcess.running` flag persists when sandbox sleeps
3. **No SIGTERM handler** in agent for graceful WebSocket closure

## Proposed Solution

Two simple changes:

1. **DO side**: Retry loop that resets `agentProcess = null` on failure
2. **Agent side**: SIGTERM handler that closes connections gracefully

---

## Phase 1: Agent SIGTERM Handler

**File:** `packages/agent/src/index.ts`

```typescript
// Add after server creation (~line 223)

// Track active connections for graceful shutdown
const activeConnections = new Set<ServerWebSocket<WebSocketData>>();

// Add to websocket.open():
activeConnections.add(ws);

// Add to websocket.close():
activeConnections.delete(ws);

// Graceful shutdown
const shutdown = async (signal: string) => {
  console.log(`[Agent] ${signal} received, closing ${activeConnections.size} connections`);

  for (const ws of activeConnections) {
    try {
      ws.close(1012, 'Server restarting');
    } catch {
      // Already closed
    }
  }

  // Brief drain period
  await new Promise(r => setTimeout(r, 500));
  process.exit(0);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
```

**Acceptance criteria:**
- [x] SIGTERM closes all WebSocket connections with code 1012
- [x] Active connections tracked in Set

---

## Phase 2: DO Retry Loop

**File:** `packages/tenant-worker/src/durable-objects/tenant-agent.ts`

Replace the current `handleWebSocketChat` method:

```typescript
private async handleWebSocketChat(
  request: Request,
  tenantId: string,
  userId: string
): Promise<Response> {
  const t0 = Date.now();
  const maxRetries = 3;
  const retryDelays = [1000, 3000, 8000]; // Accommodate cold starts

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      await this.ensureSandboxReady(tenantId, userId, t0);

      if (!this.sandbox) {
        throw new Error('Sandbox not initialized');
      }

      const wsRequest = new Request(request.url, {
        method: 'GET',
        headers: request.headers,
      });

      const response = await this.sandbox.wsConnect(wsRequest, 8080);
      console.log(`[DO] WebSocket connected: attempt=${attempt + 1}`);
      return response;

    } catch (error) {
      console.error(`[DO] WebSocket attempt ${attempt + 1} failed:`, error);

      // Reset state so next attempt triggers fresh sandbox
      this.agentProcess = null;

      if (attempt < maxRetries - 1) {
        await new Promise(r => setTimeout(r, retryDelays[attempt]));
        continue;
      }

      return new Response('WebSocket connection failed', { status: 503 });
    }
  }

  throw new Error('Unreachable');
}
```

**Acceptance criteria:**
- [x] Retries 3 times with 1s/3s/8s delays
- [x] Resets `agentProcess = null` on each failure
- [x] Returns 503 after exhausting retries

---

## Testing

### Manual Tests

1. **Idle recovery**: Keep WebSocket idle for 5 minutes, send message, verify response
2. **Sandbox sleep recovery**: Stop sandbox container, reconnect, verify recovery within 12s
3. **SIGTERM**: Send SIGTERM to agent container, verify connections close with code 1012

---

## Notes

### Why No Circuit Breaker?

DHH: "You have one DO talking to one sandbox. The retry loop is already rate-limiting failures. A circuit breaker here is cargo cult engineering."

### Why No Mutex?

Code Simplicity Reviewer: "DOs are single-threaded. The JavaScript event loop already serializes access. A mutex for concurrent requests is solving a problem that doesn't exist."

### Why No Heartbeat?

Bun handles ping/pong automatically with `sendPings: true` (default) and `idleTimeout: 120`. No manual heartbeat needed.

---

## References

- Current WebSocket handling: `packages/tenant-worker/src/durable-objects/tenant-agent.ts:530-593`
- Agent WebSocket server: `packages/agent/src/index.ts:86-223`
- [Bun WebSocket API](https://bun.com/docs/api/websockets) - auto ping/pong
- [GitHub: Outgoing WebSocket Hibernation Not Supported](https://github.com/cloudflare/workerd/issues/4864)
