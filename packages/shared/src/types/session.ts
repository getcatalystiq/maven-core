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
