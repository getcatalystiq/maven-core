-- Remove oauth_provider column from connectors table
-- OAuth endpoints are now discovered from MCP server's .well-known/oauth-authorization-server

-- SQLite doesn't support DROP COLUMN directly before 3.35.0
-- Create new table without oauth_provider, copy data, swap tables

-- Create new connectors table without oauth_provider
CREATE TABLE connectors_new (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  config TEXT NOT NULL,
  oauth_client_id TEXT,
  oauth_scopes TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(tenant_id, name),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- Copy data from old table (excluding oauth_provider)
INSERT INTO connectors_new (id, tenant_id, name, type, config, oauth_client_id, oauth_scopes, enabled, created_at)
SELECT id, tenant_id, name, type, config, oauth_client_id, oauth_scopes, enabled, created_at
FROM connectors;

-- Drop old table
DROP TABLE connectors;

-- Rename new table to connectors
ALTER TABLE connectors_new RENAME TO connectors;

-- Recreate index
CREATE INDEX IF NOT EXISTS idx_connectors_tenant_id ON connectors(tenant_id);
