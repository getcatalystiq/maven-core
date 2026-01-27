/**
 * Internal routes - for sandbox to fetch configuration
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { listSkillsForUser } from '../services/skills';
import { listEnabledConnectors, getConnectorToken } from '../services/connectors';
import { getUserById, getTenantBySlug, listTenants } from '../services/database';
import type { Env } from '../index';
import type { SandboxConfig, SkillMetadata, ConnectorMetadata } from '@maven/shared';

/**
 * Validate path component to prevent path traversal attacks
 * Rejects any path containing '..' or starting with '/'
 */
function isValidPathComponent(component: string): boolean {
  // Reject empty components
  if (!component) return false;

  // Reject path traversal sequences
  if (component.includes('..')) return false;

  // Reject absolute paths
  if (component.startsWith('/')) return false;

  // Reject null bytes
  if (component.includes('\0')) return false;

  // Only allow alphanumeric, underscore, hyphen, and dot
  // This is stricter but safer for file paths
  return /^[a-zA-Z0-9_\-\.]+$/.test(component);
}

const app = new Hono<{ Bindings: Env }>();

// Get configuration for a tenant/user sandbox
app.get('/config/:tenantId/:userId', async (c) => {
  const tenantId = c.req.param('tenantId');
  const userId = c.req.param('userId');

  // Get user to determine roles
  const user = await getUserById(c.env.DB, userId);
  if (!user || user.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'User not found' });
  }

  // Get skills accessible to this user
  const skills = await listSkillsForUser(c.env.DB, tenantId, userId, user.roles);
  const skillMetadata: SkillMetadata[] = skills.map((s) => ({
    id: s.id,
    name: s.name,
    description: s.description,
    r2Path: s.r2Path,
    roles: s.roles,
  }));

  // Get enabled connectors for tenant
  const connectors = await listEnabledConnectors(c.env.DB, tenantId);

  // Get tokens for each connector
  const connectorMetadata: ConnectorMetadata[] = await Promise.all(
    connectors.map(async (conn) => {
      const token = await getConnectorToken(c.env.KV, tenantId, userId, conn.id);
      // Map ConnectorConfig to ConnectorMetadata.config format
      const config: ConnectorMetadata['config'] = {
        command: 'command' in conn.config ? conn.config.command : undefined,
        args: 'args' in conn.config ? conn.config.args : undefined,
        url: 'url' in conn.config ? conn.config.url : undefined,
        headers: 'headers' in conn.config ? conn.config.headers : undefined,
        env: 'env' in conn.config ? conn.config.env : undefined,
      };
      return {
        id: conn.id,
        name: conn.name,
        type: conn.type,
        config,
        accessToken: token?.accessToken,
      };
    })
  );

  const config: SandboxConfig = {
    tenantId,
    userId,
    skills: skillMetadata,
    connectors: connectorMetadata,
  };

  return c.json(config);
});

// Get skill content from R2
app.get('/skills/:tenantId/:skillName/*', async (c) => {
  const tenantId = c.req.param('tenantId');
  const skillName = c.req.param('skillName');
  const pathSegment = c.req.path.split(`/skills/${tenantId}/${skillName}/`)[1] || 'SKILL.md';

  // Validate path components to prevent path traversal attacks
  if (!isValidPathComponent(tenantId)) {
    throw new HTTPException(400, { message: 'Invalid tenant ID' });
  }

  if (!isValidPathComponent(skillName)) {
    throw new HTTPException(400, { message: 'Invalid skill name' });
  }

  // Validate each segment of the path
  const pathParts = pathSegment.split('/');
  for (const part of pathParts) {
    if (!isValidPathComponent(part)) {
      throw new HTTPException(400, { message: 'Invalid path: contains forbidden characters' });
    }
  }

  const r2Path = `skills/${tenantId}/${skillName}/${pathSegment}`;
  const object = await c.env.FILES.get(r2Path);

  if (!object) {
    throw new HTTPException(404, { message: 'Skill file not found' });
  }

  const content = await object.text();
  return c.text(content);
});

// Get tenant configuration by slug (for wrangler deployment)
app.get('/tenant/:slug', async (c) => {
  const slug = c.req.param('slug');

  if (!isValidPathComponent(slug)) {
    throw new HTTPException(400, { message: 'Invalid tenant slug' });
  }

  const tenant = await getTenantBySlug(c.env.DB, slug);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  // Return config for wrangler deployment
  return c.json({
    id: tenant.id,
    slug: tenant.slug,
    name: tenant.name,
    tier: tenant.tier,
    enabled: tenant.enabled,
    settings: tenant.settings,
  });
});

// List all tenants (for tenant CLI)
app.get('/tenants', async (c) => {
  const { tenants } = await listTenants(c.env.DB, 0, 100);

  return c.json({
    tenants: tenants.map((t) => ({
      id: t.id,
      slug: t.slug,
      name: t.name,
      tier: t.tier,
      enabled: t.enabled,
    })),
  });
});

export { app as internalRoutes };
