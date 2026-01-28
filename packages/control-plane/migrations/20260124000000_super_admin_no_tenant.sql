-- Allow super-admin users to have no tenant
-- Super-admins have tenant_id = NULL and can access any tenant

-- SQLite doesn't support ALTER COLUMN, so we need to recreate the table
-- First, create a new table with nullable tenant_id

CREATE TABLE IF NOT EXISTS users_new (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  tenant_id TEXT,  -- Now nullable for super-admins
  roles TEXT NOT NULL DEFAULT '["user"]',
  password_hash TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- Create unique constraint: email must be unique per tenant, or globally unique if no tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_tenant ON users_new(email, tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_global ON users_new(email) WHERE tenant_id IS NULL;

-- Copy data from old table
INSERT INTO users_new SELECT * FROM users;

-- Drop old table
DROP TABLE users;

-- Rename new table
ALTER TABLE users_new RENAME TO users;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
