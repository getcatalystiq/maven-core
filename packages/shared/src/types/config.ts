/**
 * Configuration types
 */

export interface SandboxConfig {
  tenantId: string;
  userId: string;
  sessionId?: string;  // Optional - only for session-scoped operations
  skills: SkillMetadata[];
  connectors: ConnectorMetadata[];
}

/**
 * Session workspace base path in the sandbox
 */
export const SESSIONS_BASE_PATH = '/home/maven/sessions';

/**
 * Compute session workspace path from session ID
 */
export function getSessionWorkspacePath(sessionId: string): string {
  return `${SESSIONS_BASE_PATH}/${sessionId}`;
}

/**
 * Compute session skills path from session ID
 */
export function getSessionSkillsPath(sessionId: string): string {
  return `${SESSIONS_BASE_PATH}/${sessionId}/.claude/skills`;
}

export interface SkillMetadata {
  id: string;
  name: string;
  description: string;
  r2Path: string;
  roles?: string[];
}

export interface ConnectorMetadata {
  id: string;
  name: string;
  type: 'stdio' | 'sse' | 'http';
  config: {
    command?: string;
    args?: string[];
    url?: string;
    headers?: Record<string, string>;
    env?: Record<string, string>;
  };
  accessToken?: string;
}

export interface TierLimits {
  maxUsers: number;
  maxSessions: number;
  maxSkills: number;
  maxConnectors: number;
  rateLimitPerMinute: number;
  features: string[];
}

export const TIER_LIMITS: Record<string, TierLimits> = {
  free: {
    maxUsers: 1,
    maxSessions: 10,
    maxSkills: 5,
    maxConnectors: 2,
    rateLimitPerMinute: 10,
    features: ['basic_chat'],
  },
  starter: {
    maxUsers: 5,
    maxSessions: 100,
    maxSkills: 20,
    maxConnectors: 10,
    rateLimitPerMinute: 60,
    features: ['basic_chat', 'skills', 'connectors'],
  },
  professional: {
    maxUsers: 25,
    maxSessions: 1000,
    maxSkills: 100,
    maxConnectors: 50,
    rateLimitPerMinute: 300,
    features: ['basic_chat', 'skills', 'connectors', 'custom_models', 'analytics'],
  },
  enterprise: {
    maxUsers: -1,  // Unlimited
    maxSessions: -1,
    maxSkills: -1,
    maxConnectors: -1,
    rateLimitPerMinute: 1000,
    features: ['basic_chat', 'skills', 'connectors', 'custom_models', 'analytics', 'sso', 'audit_logs'],
  },
};
