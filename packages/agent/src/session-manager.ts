/**
 * Session Manager V2 - Uses the V2 Session API for warm starts
 *
 * Instead of spawning a new subprocess for each query (~10s overhead),
 * this maintains long-lived sessions that reuse the same process.
 *
 * The V2 API avoids the AsyncIterable complexity that caused the V1 implementation to hang.
 */

import {
  unstable_v2_createSession,
  type SDKSession,
  type SDKMessage,
  type SDKSessionOptions,
} from '@anthropic-ai/claude-agent-sdk';

// Managed session state
interface ManagedSession {
  id: string;                    // Widget session ID
  sdkSessionId?: string;         // SDK session ID (from first result)
  sdkSession: SDKSession;
  tenantId: string;
  userId: string;
  userRoles: string[];
  messageCount: number;
  lastActivity: number;
  isActive: boolean;
  startTime: number;
}

// Session store
const sessions = new Map<string, ManagedSession>();

// Session timeout (10 minutes of inactivity)
const SESSION_TIMEOUT_MS = 10 * 60 * 1000;

// Cleanup interval
const CLEANUP_INTERVAL_MS = 60 * 1000;

/**
 * Build SDK session options
 *
 * Note: V2 Session API doesn't support settingSources directly.
 * Skills are loaded from the native location (~/.claude/skills/) which is
 * populated by the tenant-worker's skill injection process.
 * Role-based filtering happens at injection time.
 */
function buildSessionOptions(
  _userRoles: string[],
  model?: string
): { options: Omit<SDKSessionOptions, 'pathToClaudeCodeExecutable'> } {
  // Skills are now loaded natively from ~/.claude/skills/
  // Role filtering happens at injection time in tenant-worker
  // V2 API doesn't support settingSources, but skills should be picked up
  // from the native location automatically

  return {
    options: {
      model: model || process.env.ANTHROPIC_MODEL || 'us.anthropic.claude-opus-4-5-20251101-v1:0',
      permissionMode: 'bypassPermissions' as const,
      allowedTools: ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep'],
      // Note: mcpServers not supported in V2 session options directly
      // TODO: Add MCP server support when V2 API supports it
    },
  };
}

/**
 * Create or get an existing session
 *
 * For warm paths (existing session), this returns immediately.
 * For cold paths (new session), this creates the SDK session.
 */
export async function getOrCreateSession(
  sessionId: string,
  tenantId: string,
  userId: string,
  userRoles: string[] = ['user'],
  model?: string
): Promise<ManagedSession> {
  // Check for existing active session (WARM PATH)
  const existing = sessions.get(sessionId);
  if (existing?.isActive) {
    existing.lastActivity = Date.now();
    console.log(`[SESSION] Reusing existing session ${sessionId} (${existing.messageCount} messages)`);
    return existing;
  }

  // Create new session (COLD PATH)
  console.log(`[SESSION] Creating new session ${sessionId}`);
  const t0 = Date.now();

  // Build configuration
  // Skills are loaded natively from ~/.claude/skills/ (injected by tenant-worker)
  const { options } = buildSessionOptions(userRoles, model);
  console.log(`[SESSION] Config built in ${Date.now() - t0}ms (native skill loading)`);

  // Create V2 SDK session
  // Skills are loaded from native location ~/.claude/skills/
  const sdkSession = unstable_v2_createSession({
    ...options,
    pathToClaudeCodeExecutable: '/usr/local/bin/claude',
  });

  const session: ManagedSession = {
    id: sessionId,
    sdkSession,
    tenantId,
    userId,
    userRoles,
    messageCount: 0,
    lastActivity: Date.now(),
    isActive: true,
    startTime: Date.now(),
  };

  sessions.set(sessionId, session);
  console.log(`[SESSION] Session ${sessionId} created, SDK session initialized`);

  return session;
}

/**
 * Try to get an existing session, returns null if not found
 */
export function getSession(sessionId: string): ManagedSession | null {
  const session = sessions.get(sessionId);
  if (session?.isActive) {
    return session;
  }
  return null;
}

/**
 * Send a message to a session and get the response stream
 *
 * This is the core streaming function that:
 * 1. Sends the user message to the SDK session
 * 2. Yields all SDK messages (assistant, tool_use, stream_event, etc.)
 * 3. Captures the SDK session ID from the result message
 */
export async function* sendMessage(
  session: ManagedSession,
  message: string,
  signal?: AbortSignal
): AsyncGenerator<SDKMessage> {
  const t0 = Date.now();
  session.lastActivity = Date.now();
  session.messageCount++;

  console.log(`[SESSION] Sending message #${session.messageCount} to session ${session.id}`);

  try {
    // Send message to SDK session
    await session.sdkSession.send(message);

    // Stream responses
    let firstResponse = true;
    for await (const msg of session.sdkSession.stream()) {
      // Check if client disconnected
      if (signal?.aborted) {
        console.log(`[SESSION] Client disconnected, stopping stream for session ${session.id}`);
        return;
      }

      if (firstResponse) {
        console.log(`[SESSION] First response in ${Date.now() - t0}ms (type: ${msg.type})`);
        firstResponse = false;
      }

      yield msg;

      // Result marks the end of this turn
      if (msg.type === 'result') {
        // Capture SDK session ID for potential future resume
        if ('session_id' in msg) {
          session.sdkSessionId = msg.session_id;
        }
        console.log(`[SESSION] Message #${session.messageCount} completed in ${Date.now() - t0}ms`);
        break;
      }
    }
  } catch (error) {
    console.error(`[SESSION] Error in session ${session.id}:`, error);
    // Mark session as inactive on error
    session.isActive = false;
    throw error;
  }
}

/**
 * Close a session and clean up resources
 */
export function closeSession(sessionId: string): void {
  const session = sessions.get(sessionId);
  if (session) {
    console.log(`[SESSION] Closing session ${sessionId} (${session.messageCount} messages, ${Date.now() - session.startTime}ms lifetime)`);
    try {
      session.sdkSession.close();
    } catch (error) {
      console.error(`[SESSION] Error closing SDK session:`, error);
    }
    session.isActive = false;
    sessions.delete(sessionId);
  }
}

/**
 * Get session stats for monitoring
 */
export function getSessionStats(): {
  activeSessions: number;
  totalMessages: number;
  sessions: Array<{
    id: string;
    sdkSessionId?: string;
    messageCount: number;
    ageMs: number;
    isWarm: boolean;
  }>;
} {
  const now = Date.now();
  const sessionList = Array.from(sessions.values()).map((s) => ({
    id: s.id,
    sdkSessionId: s.sdkSessionId,
    messageCount: s.messageCount,
    ageMs: now - s.startTime,
    isWarm: s.messageCount > 0,
  }));

  return {
    activeSessions: sessions.size,
    totalMessages: sessionList.reduce((sum, s) => sum + s.messageCount, 0),
    sessions: sessionList,
  };
}

/**
 * Cleanup stale sessions
 */
function cleanupStaleSessions(): void {
  const now = Date.now();
  const stale: string[] = [];

  for (const [id, session] of sessions) {
    if (now - session.lastActivity > SESSION_TIMEOUT_MS) {
      stale.push(id);
    }
  }

  for (const id of stale) {
    console.log(`[SESSION] Cleaning up stale session ${id}`);
    closeSession(id);
  }

  if (stale.length > 0) {
    console.log(`[SESSION] Cleaned up ${stale.length} stale sessions, ${sessions.size} active`);
  }
}

// Start cleanup interval
setInterval(cleanupStaleSessions, CLEANUP_INTERVAL_MS);
