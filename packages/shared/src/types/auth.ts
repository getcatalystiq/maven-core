/**
 * Authentication and authorization types
 */

export interface User {
  id: string;
  email: string;
  tenantId: string | null;  // Null for super-admins (tenant-less users)
  roles: string[];
  passwordHash?: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string; // URL-friendly identifier (e.g., "acme-corp")
  tier: TenantTier;
  enabled: boolean;
  settings: TenantSettings;
  createdAt: string;
  updatedAt: string;
}

export type TenantTier = 'free' | 'starter' | 'professional' | 'enterprise';

export interface AgentConfig {
  model?: string;
  max_turns?: number;
  max_budget?: number;
  // Provider info (actual credentials stored in worker secrets, not here)
  llm_provider?: 'anthropic' | 'aws-bedrock';
  llm_configured?: boolean;
}

export interface TenantSettings {
  maxUsers: number;
  maxSessions: number;
  maxSkills: number;
  maxConnectors: number;
  rateLimitPerMinute: number;
  features: string[];
  // Deployment info (set during provisioning)
  worker_url?: string;
  container_id?: string;
  // Agent configuration
  agent?: AgentConfig;
}

export interface Role {
  id: string;
  tenantId: string;
  name: string;
  permissions: string[];
  createdAt: string;
}

export interface JWTPayload {
  sub: string;           // user_id
  tenant_id: string | null;  // Null for super-admins
  roles: string[];
  type?: 'access' | 'refresh';  // Token type (refresh tokens have 'refresh')
  iat: number;
  exp: number;
}

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
}

export interface AuthContext {
  userId: string;
  tenantId: string | null;  // Null for super-admins
  roles: string[];
}
