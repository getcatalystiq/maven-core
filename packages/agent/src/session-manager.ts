/**
 * Session Manager - Keeps Claude Agent SDK processes alive using streaming input mode
 *
 * Instead of spawning a new subprocess for each query (~10s overhead),
 * this maintains long-lived sessions that reuse the same process.
 *
 * @see https://platform.claude.com/docs/en/agent-sdk/streaming-vs-single-mode
 */

import { query, type SDKMessage, type McpServerConfig, type SDKUserMessage } from '@anthropic-ai/claude-agent-sdk';
import { loadSkills, filterSkillsByRoles, buildSystemPromptFromSkills } from './skills/loader';
import { buildMcpServers, parseConnectorsFromEnv } from './mcp/servers';

// Internal message to signal session end
interface EndMessage {
  type: 'end';
}

type InputMessage = SDKUserMessage | EndMessage;

// Session state
interface AgentSession {
  id: string;
  tenantId: string;
  userId: string;
  userRoles: string[];
  model?: string;
  // Channel for pushing messages to the generator
  messageChannel: {
    push: (msg: InputMessage) => void;
    iterator: AsyncIterableIterator<InputMessage>;
  };
  // Iterator for reading SDK responses
  responseIterator: AsyncIterableIterator<SDKMessage>;
  // Tracking
  lastActivity: number;
  messageCount: number;
  isActive: boolean;
  startTime: number;
}

// Session store
const sessions = new Map<string, AgentSession>();

// Session timeout (10 minutes of inactivity)
const SESSION_TIMEOUT_MS = 10 * 60 * 1000;

// Cleanup interval
const CLEANUP_INTERVAL_MS = 60 * 1000;

/**
 * Create an async channel for message passing
 * This allows external code to push messages that the generator yields
 */
function createMessageChannel(): {
  push: (msg: InputMessage) => void;
  iterator: AsyncIterableIterator<InputMessage>;
} {
  const queue: InputMessage[] = [];
  let resolve: ((value: IteratorResult<InputMessage>) => void) | null = null;
  let ended = false;

  const push = (msg: InputMessage) => {
    if (ended) return;

    if (msg.type === 'end') {
      ended = true;
    }

    if (resolve) {
      // Someone is waiting, resolve immediately
      const r = resolve;
      resolve = null;
      r({ value: msg, done: msg.type === 'end' });
    } else {
      // No one waiting, queue it
      queue.push(msg);
    }
  };

  const iterator: AsyncIterableIterator<InputMessage> = {
    [Symbol.asyncIterator]() {
      return this;
    },
    async next(): Promise<IteratorResult<InputMessage>> {
      if (queue.length > 0) {
        const msg = queue.shift()!;
        return { value: msg, done: msg.type === 'end' };
      }

      if (ended) {
        return { value: undefined as unknown as InputMessage, done: true };
      }

      // Wait for next message
      return new Promise((r) => {
        resolve = r;
      });
    },
  };

  return { push, iterator };
}

/**
 * Create message generator for streaming input mode
 */
async function* createMessageGenerator(
  channel: AsyncIterableIterator<InputMessage>
): AsyncGenerator<SDKUserMessage> {
  for await (const msg of channel) {
    if (msg.type === 'end') {
      break;
    }
    yield msg as SDKUserMessage;
  }
}

/**
 * Build query options for the SDK
 */
function buildQueryOptions(
  systemPrompt: string,
  mcpServers: Record<string, McpServerConfig>,
  model?: string
) {
  return {
    model: model || process.env.ANTHROPIC_MODEL || 'us.anthropic.claude-opus-4-5-20251101-v1:0',
    includePartialMessages: true,
    permissionMode: 'bypassPermissions' as const,
    cwd: process.env.WORKSPACE_PATH || process.cwd(),
    allowedTools: ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep'] as string[],
    systemPrompt,
    mcpServers: Object.keys(mcpServers).length > 0 ? mcpServers : undefined,
    pathToClaudeCodeExecutable: '/usr/local/bin/claude',
  };
}

/**
 * Create or get an existing session
 */
export async function getOrCreateSession(
  sessionId: string,
  tenantId: string,
  userId: string,
  userRoles: string[] = ['user'],
  model?: string
): Promise<AgentSession> {
  // Check for existing session
  const existing = sessions.get(sessionId);
  if (existing && existing.isActive) {
    existing.lastActivity = Date.now();
    console.log(`[SESSION] Reusing existing session ${sessionId} (${existing.messageCount} messages)`);
    return existing;
  }

  // Create new session
  console.log(`[SESSION] Creating new session ${sessionId}`);
  const t0 = Date.now();

  // Load skills and build config
  const allSkills = await loadSkills();
  const skills = filterSkillsByRoles(allSkills, userRoles);
  const connectors = parseConnectorsFromEnv();
  const mcpServers = buildMcpServers(connectors);
  const systemPrompt = buildSystemPromptFromSkills(skills);

  console.log(`[SESSION] Config built in ${Date.now() - t0}ms (${skills.length} skills, ${systemPrompt.length} chars)`);

  // Create message channel
  const messageChannel = createMessageChannel();

  // Start SDK with streaming input
  const messageGenerator = createMessageGenerator(messageChannel.iterator);
  const responseIterator = query({
    prompt: messageGenerator,
    options: buildQueryOptions(systemPrompt, mcpServers, model),
  })[Symbol.asyncIterator]();

  const session: AgentSession = {
    id: sessionId,
    tenantId,
    userId,
    userRoles,
    model,
    messageChannel,
    responseIterator,
    lastActivity: Date.now(),
    messageCount: 0,
    isActive: true,
    startTime: Date.now(),
  };

  sessions.set(sessionId, session);
  console.log(`[SESSION] Session ${sessionId} created, SDK process started`);

  return session;
}

/**
 * Send a message to a session and get the response stream
 */
export async function* sendMessage(
  session: AgentSession,
  message: string
): AsyncGenerator<SDKMessage> {
  const t0 = Date.now();
  session.lastActivity = Date.now();
  session.messageCount++;

  console.log(`[SESSION] Sending message #${session.messageCount} to session ${session.id}`);

  // Push message to the generator (SDKUserMessage format)
  const userMessage: SDKUserMessage = {
    type: 'user',
    message: {
      role: 'user',
      content: message,
    },
    parent_tool_use_id: null,
    session_id: session.id,
  };
  session.messageChannel.push(userMessage);

  // Read responses until we get a result or the next message starts
  let firstResponse = true;
  let receivedResult = false;

  while (!receivedResult) {
    const { value: msg, done } = await session.responseIterator.next();

    if (done) {
      console.log(`[SESSION] Session ${session.id} ended unexpectedly`);
      session.isActive = false;
      break;
    }

    if (firstResponse) {
      console.log(`[SESSION] First response in ${Date.now() - t0}ms (type: ${msg.type})`);
      firstResponse = false;
    }

    yield msg;

    // Result marks the end of this turn
    if (msg.type === 'result') {
      receivedResult = true;
      console.log(`[SESSION] Message #${session.messageCount} completed in ${Date.now() - t0}ms`);
    }
  }
}

/**
 * Close a session
 */
export function closeSession(sessionId: string): void {
  const session = sessions.get(sessionId);
  if (session) {
    console.log(`[SESSION] Closing session ${sessionId} (${session.messageCount} messages, ${Date.now() - session.startTime}ms lifetime)`);
    session.messageChannel.push({ type: 'end' });
    session.isActive = false;
    sessions.delete(sessionId);
  }
}

/**
 * Get session stats
 */
export function getSessionStats(): {
  activeSessions: number;
  totalMessages: number;
  sessions: Array<{ id: string; messageCount: number; ageMs: number }>;
} {
  const now = Date.now();
  const sessionList = Array.from(sessions.values()).map((s) => ({
    id: s.id,
    messageCount: s.messageCount,
    ageMs: now - s.startTime,
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
