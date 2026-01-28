/**
 * Session and message types
 */

export interface Session {
  id: string;
  tenantId: string;
  userId: string;
  status: SessionStatus;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export type SessionStatus = 'active' | 'completed' | 'error';

export interface Message {
  id: string;
  sessionId: string;
  role: MessageRole;
  content: MessageContent[];
  toolCalls?: ToolCall[];
  metadata?: Record<string, unknown>;
  createdAt: string;
}

export type MessageRole = 'user' | 'assistant' | 'system';

export type MessageContent =
  | TextContent
  | ImageContent
  | ToolResultContent;

export interface TextContent {
  type: 'text';
  text: string;
}

export interface ImageContent {
  type: 'image';
  source: ImageSource;
}

export interface ImageSource {
  type: 'base64' | 'url';
  mediaType?: string;
  data?: string;
  url?: string;
}

export interface ToolResultContent {
  type: 'tool_result';
  toolUseId: string;
  content: string;
  isError?: boolean;
}

export interface ToolCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ChatResponse {
  response: string;
  sessionId: string;
  usage?: UsageStats;
}

export interface UsageStats {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
}

export interface StreamEvent {
  type: 'content' | 'tool_use' | 'done' | 'error';
  data: unknown;
}

/**
 * Session metadata stored in KV for persistence
 * Key: session:{tenantId}:{sessionId}
 * TTL: 90 days (SESSION_TTL_SECONDS)
 */
export interface SessionMetadata {
  /** Owner user ID - validated on each request for security */
  userId: string;
  /** Session status */
  status: SessionStatus;
  /** ISO 8601 timestamp of session creation */
  createdAt: string;
  /** ISO 8601 timestamp of last activity */
  lastActivity: string;
  /** Number of messages in session */
  messageCount: number;
  /** Cumulative input tokens used */
  totalInputTokens: number;
  /** Cumulative output tokens used */
  totalOutputTokens: number;
}

/**
 * Message stored in R2 for history
 * Path: sessions/{tenantId}/{sessionId}/{timestamp}.ndjson (batch files)
 * TTL: 90 days (enforced via cleanup job)
 */
export interface StoredMessage {
  /** Unique message ID */
  id: string;
  /** ISO 8601 timestamp */
  timestamp: string;
  /** Message role */
  role: MessageRole;
  /** Message content as text */
  content: string;
  /** Token usage for this message */
  usage?: UsageStats;
}
