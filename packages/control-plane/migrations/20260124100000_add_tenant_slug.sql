-- Add slug column to tenants table for URL-friendly identifiers
-- Used for dedicated worker and container naming

-- Add slug column with default value based on id
ALTER TABLE tenants ADD COLUMN slug TEXT;

-- Set default slugs for existing tenants based on their id
UPDATE tenants SET slug = id WHERE slug IS NULL;

-- Create unique index on slug for fast lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_slug ON tenants(slug);
