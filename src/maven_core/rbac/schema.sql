-- Maven Core RBAC Schema
-- Run this to initialize the database tables for authentication and authorization

-- Roles table
CREATE TABLE IF NOT EXISTS roles (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, name)
);

-- Default roles (for new tenants)
INSERT OR IGNORE INTO roles (id, tenant_id, name, description) VALUES
    ('role-admin', 'default', 'admin', 'Full access to all resources'),
    ('role-user', 'default', 'user', 'Standard user access'),
    ('role-service', 'default', 'service', 'Service account access');

-- Users table (for built-in auth)
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT,
    email_verified INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(tenant_id, email)
);

-- User-role assignments
CREATE TABLE IF NOT EXISTS user_roles (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, user_id, role_id),
    FOREIGN KEY (role_id) REFERENCES roles(id)
);

-- Skill-role assignments (which roles can access which skills)
CREATE TABLE IF NOT EXISTS skill_roles (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    skill_slug TEXT NOT NULL,
    role_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, skill_slug, role_id),
    FOREIGN KEY (role_id) REFERENCES roles(id)
);

-- Service accounts
CREATE TABLE IF NOT EXISTS service_accounts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    jwt_jti TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    revoked_at TIMESTAMP,
    UNIQUE(tenant_id, name)
);

-- OAuth tokens (encrypted)
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    connector_slug TEXT NOT NULL,
    access_token_encrypted TEXT NOT NULL,
    refresh_token_encrypted TEXT,
    token_type TEXT DEFAULT 'Bearer',
    scopes TEXT,
    expires_at TIMESTAMP,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(tenant_id, user_id, connector_slug)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_users_tenant_email ON users(tenant_id, email);
CREATE INDEX IF NOT EXISTS idx_user_roles_tenant_user ON user_roles(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_skill_roles_tenant_skill ON skill_roles(tenant_id, skill_slug);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_tenant_user ON oauth_tokens(tenant_id, user_id);
