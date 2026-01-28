/**
 * Zod validation schemas
 */

import { z } from 'zod';

// Email validation
export const emailSchema = z
  .string()
  .email('Invalid email format')
  .min(3)
  .max(254);

// Password validation (relaxed for dev)
export const passwordSchema = z
  .string()
  .min(8, 'Password must be at least 8 characters')
  .max(128, 'Password must be at most 128 characters');

// UUID validation
export const uuidSchema = z.string().uuid();

// Session ID validation (UUID format for security)
export const sessionIdSchema = z.string().uuid('Session ID must be a valid UUID');

// Tenant ID validation (UUID format)
export const tenantIdSchema = z.string().uuid('Tenant ID must be a valid UUID');

// Role name validation
export const roleNameSchema = z
  .string()
  .min(1)
  .max(64)
  .regex(/^[a-zA-Z][a-zA-Z0-9_-]*$/, 'Role name must start with a letter');

// Skill name validation
export const skillNameSchema = z
  .string()
  .min(1)
  .max(64)
  .regex(/^[a-zA-Z][a-zA-Z0-9_-]*$/, 'Skill name must start with a letter');

// Connector name validation
export const connectorNameSchema = z
  .string()
  .min(1)
  .max(64)
  .regex(/^[a-zA-Z][a-zA-Z0-9_-]*$/, 'Connector name must start with a letter');

// Auth schemas
export const loginRequestSchema = z.object({
  email: emailSchema,
  password: z.string().min(1),
});

export const registerRequestSchema = z.object({
  email: emailSchema,
  password: passwordSchema,
  tenantId: tenantIdSchema.optional(),
});

export const refreshTokenRequestSchema = z.object({
  refresh_token: z.string().min(1),
});

// User schemas
export const createUserSchema = z.object({
  email: emailSchema,
  password: passwordSchema,
  roles: z.array(roleNameSchema).optional().default(['user']),
});

export const updateUserSchema = z.object({
  email: emailSchema.optional(),
  password: passwordSchema.optional(),
  roles: z.array(roleNameSchema).optional(),
  enabled: z.boolean().optional(),
});

// Slug validation
export const slugSchema = z
  .string()
  .min(1)
  .max(50)
  .regex(/^[a-z0-9-]+$/, 'Slug must be lowercase alphanumeric with hyphens');

// Tenant schemas
export const createTenantSchema = z.object({
  id: tenantIdSchema.optional(), // Auto-generated UUID if not provided
  name: z.string().min(1).max(256),
  slug: slugSchema.optional(), // URL-friendly identifier, auto-generated from name if not provided
  tier: z.enum(['free', 'starter', 'professional', 'enterprise']).default('free'),
});

export const updateTenantSchema = z.object({
  name: z.string().min(1).max(256).optional(),
  tier: z.enum(['free', 'starter', 'professional', 'enterprise']).optional(),
  enabled: z.boolean().optional(),
});

// LLM provider types
export const llmProviderSchema = z.enum(['anthropic', 'aws-bedrock']);

// LLM credentials schema for tenant configuration
export const llmCredentialsSchema = z.discriminatedUnion('provider', [
  z.object({
    provider: z.literal('anthropic'),
    anthropic_api_key: z.string().min(1),
  }),
  z.object({
    provider: z.literal('aws-bedrock'),
    aws_access_key_id: z.string().min(1),
    aws_secret_access_key: z.string().min(1),
    aws_region: z.string().default('us-east-1'),
  }),
]);

// Agent settings schema
export const agentSettingsSchema = z.object({
  model: z.string().optional(),
  max_turns: z.number().int().min(1).max(100).optional(),
  max_budget: z.number().positive().optional(),
  llm: llmCredentialsSchema.optional(),
});

// Update tenant settings (includes agent settings with LLM credentials)
export const updateTenantSettingsSchema = z.object({
  settings: z.object({
    agent: agentSettingsSchema.optional(),
  }),
});

// Skill schemas
export const createSkillSchema = z.object({
  name: skillNameSchema,
  description: z.string().max(1024).optional(),
  content: z.string().min(1),  // SKILL.md content
  roles: z.array(roleNameSchema).optional(),
});

export const updateSkillSchema = z.object({
  description: z.string().max(1024).optional(),
  content: z.string().optional(),
  roles: z.array(roleNameSchema).optional(),
  enabled: z.boolean().optional(),
});

// Connector schemas
export const stdioConfigSchema = z.object({
  type: z.literal('stdio'),
  command: z.string().min(1),
  args: z.array(z.string()).optional(),
  env: z.record(z.string(), z.string()).optional(),
});

export const sseConfigSchema = z.object({
  type: z.literal('sse'),
  url: z.string().url(),
  headers: z.record(z.string(), z.string()).optional(),
});

export const httpConfigSchema = z.object({
  type: z.literal('http'),
  url: z.string().url(),
  headers: z.record(z.string(), z.string()).optional(),
});

export const connectorConfigSchema = z.discriminatedUnion('type', [
  stdioConfigSchema,
  sseConfigSchema,
  httpConfigSchema,
]);

export const createConnectorSchema = z.object({
  name: connectorNameSchema,
  description: z.string().max(500).optional(),
  type: z.enum(['stdio', 'sse', 'http']),
  config: connectorConfigSchema,
  oauthClientId: z.string().optional(),
  oauthClientSecret: z.string().optional(),
  oauthScopes: z.array(z.string()).optional(),
});

export const updateConnectorSchema = z.object({
  name: connectorNameSchema.optional(),
  description: z.string().max(500).optional(),
  config: connectorConfigSchema.optional(),
  oauthScopes: z.array(z.string()).optional(),
  enabled: z.boolean().optional(),
});

// Widget-specific schemas
export const oauthInitiateSchema = z.object({
  redirectUri: z.string().url(),
});

// Chat schemas
export const chatRequestSchema = z.object({
  message: z.string().min(1).max(100000),
  sessionId: sessionIdSchema.optional(),
  sessionPath: z.string().optional(), // Session workspace path for native skill loading
  skills: z.array(skillNameSchema).optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

// Pagination schemas
export const paginationSchema = z.object({
  offset: z.coerce.number().int().min(0).default(0),
  limit: z.coerce.number().int().min(1).max(100).default(20),
});

// Type exports
export type LoginRequest = z.infer<typeof loginRequestSchema>;
export type RegisterRequest = z.infer<typeof registerRequestSchema>;
export type RefreshTokenRequest = z.infer<typeof refreshTokenRequestSchema>;
export type CreateUserRequest = z.infer<typeof createUserSchema>;
export type UpdateUserRequest = z.infer<typeof updateUserSchema>;
export type CreateTenantRequest = z.infer<typeof createTenantSchema>;
export type UpdateTenantRequest = z.infer<typeof updateTenantSchema>;
export type CreateSkillRequest = z.infer<typeof createSkillSchema>;
export type UpdateSkillRequest = z.infer<typeof updateSkillSchema>;
export type CreateConnectorRequest = z.infer<typeof createConnectorSchema>;
export type UpdateConnectorRequest = z.infer<typeof updateConnectorSchema>;
export type ChatRequest = z.infer<typeof chatRequestSchema>;
export type PaginationParams = z.infer<typeof paginationSchema>;
export type LLMProvider = z.infer<typeof llmProviderSchema>;
export type LLMCredentials = z.infer<typeof llmCredentialsSchema>;
export type AgentSettings = z.infer<typeof agentSettingsSchema>;
export type UpdateTenantSettingsRequest = z.infer<typeof updateTenantSettingsSchema>;
export type OAuthInitiateRequest = z.infer<typeof oauthInitiateSchema>;
export type SessionId = z.infer<typeof sessionIdSchema>;
