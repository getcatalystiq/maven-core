/**
 * Tenant management admin routes
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import {
  createTenantSchema,
  updateTenantSchema,
  updateTenantSettingsSchema,
  paginationSchema,
  createUserSchema,
  updateUserSchema,
  hashPassword,
  TIER_LIMITS,
} from '@maven/shared';
import {
  createTenant,
  getTenantById,
  getTenantBySlug,
  listTenants,
  updateTenant,
  deleteTenant,
  createUser,
  getUserById,
  getUserByEmail,
  listUsers,
  updateUser,
  deleteUser,
} from '../../services/database';
import { deleteAllUserTokens } from '../../services/connectors';
import { deleteTenantWorker, stopAgentContainer, updateWorkerSecrets } from '../../services/worker-deploy';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// Transform tenant to API response format
function toTenantResponse(tenant: Awaited<ReturnType<typeof getTenantById>>) {
  if (!tenant) return null;
  return {
    tenant_id: tenant.id,
    name: tenant.name,
    slug: tenant.slug,
    tier: tenant.tier,
    status: tenant.enabled ? 'active' : 'suspended',
    created_at: Math.floor(new Date(tenant.createdAt).getTime() / 1000),
    updated_at: Math.floor(new Date(tenant.updatedAt).getTime() / 1000),
    limits: tenant.settings,
    settings: {
      auth_mode: 'builtin' as const,
      worker_url: tenant.settings.worker_url,
      container_id: tenant.settings.container_id,
      agent: tenant.settings.agent ? {
        model: tenant.settings.agent.model,
        max_turns: tenant.settings.agent.max_turns,
        max_budget: tenant.settings.agent.max_budget,
        llm: tenant.settings.agent.llm_provider ? {
          provider: tenant.settings.agent.llm_provider,
          // Credentials are stored in worker secrets, not returned here
          // Just indicate if they're configured
        } : undefined,
      } : undefined,
    },
  };
}

// List tenants
app.get('/', zValidator('query', paginationSchema), async (c) => {
  const { offset, limit } = c.req.valid('query');

  const result = await listTenants(c.env.DB, offset, limit);

  return c.json({
    tenants: result.tenants.map(toTenantResponse),
    total: result.total,
    offset,
    limit,
  });
});

// Get single tenant
app.get('/:id', async (c) => {
  const id = c.req.param('id');

  const tenant = await getTenantById(c.env.DB, id);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  return c.json(toTenantResponse(tenant));
});

// Helper to generate slug from name
function generateSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .substring(0, 50);
}

// Create tenant
app.post('/', zValidator('json', createTenantSchema), async (c) => {
  const { id: providedId, name, slug: providedSlug, tier } = c.req.valid('json');

  // Generate UUID if not provided
  const id = providedId || crypto.randomUUID();

  // Generate slug from name if not provided
  const slug = providedSlug || generateSlug(name);

  // Check if tenant already exists
  const existingTenant = await getTenantById(c.env.DB, id);
  if (existingTenant) {
    throw new HTTPException(409, { message: 'Tenant already exists' });
  }

  // Check if slug already exists
  const existingSlug = await getTenantBySlug(c.env.DB, slug);
  if (existingSlug) {
    throw new HTTPException(409, { message: 'Tenant with this slug already exists' });
  }

  const tenant = await createTenant(c.env.DB, {
    id,
    name,
    slug,
    tier,
    enabled: true,
    settings: TIER_LIMITS[tier],
  });

  return c.json(toTenantResponse(tenant), 201);
});

// Update tenant
app.patch('/:id', zValidator('json', updateTenantSchema), async (c) => {
  const id = c.req.param('id');
  const updates = c.req.valid('json');

  const tenant = await getTenantById(c.env.DB, id);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  // Update settings if tier changed
  let settings = tenant.settings;
  if (updates.tier && updates.tier !== tenant.tier) {
    settings = TIER_LIMITS[updates.tier];
  }

  await updateTenant(c.env.DB, id, {
    name: updates.name,
    tier: updates.tier,
    enabled: updates.enabled,
    settings,
  });

  const updatedTenant = await getTenantById(c.env.DB, id);
  return c.json(toTenantResponse(updatedTenant));
});

// Update tenant settings (includes LLM credentials)
app.put('/:id', zValidator('json', updateTenantSettingsSchema), async (c) => {
  const id = c.req.param('id');
  const { settings } = c.req.valid('json');

  const tenant = await getTenantById(c.env.DB, id);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  // Handle LLM credentials - update worker secrets
  if (settings.agent?.llm && tenant.slug) {
    const workerName = `maven-tenant-${tenant.slug}`;
    const llm = settings.agent.llm;

    // Prepare secrets based on provider
    const secrets: Record<string, string> = {};

    if (llm.provider === 'anthropic') {
      secrets['ANTHROPIC_API_KEY'] = llm.anthropic_api_key;
      // Clear bedrock flag when using Anthropic
      secrets['CLAUDE_CODE_USE_BEDROCK'] = '0';
    } else if (llm.provider === 'aws-bedrock') {
      secrets['AWS_ACCESS_KEY_ID'] = llm.aws_access_key_id;
      secrets['AWS_SECRET_ACCESS_KEY'] = llm.aws_secret_access_key;
      secrets['AWS_REGION'] = llm.aws_region || 'us-east-1';
      secrets['CLAUDE_CODE_USE_BEDROCK'] = '1';
    }

    // Update model if provided
    if (settings.agent.model) {
      secrets['ANTHROPIC_MODEL'] = settings.agent.model;
    }

    try {
      await updateWorkerSecrets(workerName, secrets, c.env);
    } catch (err) {
      console.error(`Failed to update worker secrets for ${workerName}:`, err);
      throw new HTTPException(500, {
        message: 'Failed to update LLM credentials on tenant worker',
      });
    }
  }

  // Update tenant settings in database (excluding sensitive credentials)
  const newSettings = {
    ...tenant.settings,
    agent: {
      model: settings.agent?.model || tenant.settings.agent?.model,
      max_turns: settings.agent?.max_turns || tenant.settings.agent?.max_turns,
      max_budget: settings.agent?.max_budget || tenant.settings.agent?.max_budget,
      // Store provider info but NOT the actual secrets
      llm_provider: settings.agent?.llm?.provider,
      llm_configured: !!settings.agent?.llm,
    },
  };

  await updateTenant(c.env.DB, id, { settings: newSettings });

  const updatedTenant = await getTenantById(c.env.DB, id);
  return c.json(toTenantResponse(updatedTenant));
});

// Suspend tenant
app.post('/:id/suspend', async (c) => {
  const id = c.req.param('id');

  const tenant = await getTenantById(c.env.DB, id);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  await updateTenant(c.env.DB, id, { enabled: false });
  return c.json({ message: 'Tenant suspended' });
});

// Activate tenant
app.post('/:id/activate', async (c) => {
  const id = c.req.param('id');

  const tenant = await getTenantById(c.env.DB, id);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  await updateTenant(c.env.DB, id, { enabled: true });
  return c.json({ message: 'Tenant activated' });
});

// Delete tenant
app.delete('/:id', async (c) => {
  const id = c.req.param('id');
  const currentTenantId = c.get('tenantId');

  // Prevent deleting current tenant
  if (id === currentTenantId) {
    throw new HTTPException(400, { message: 'Cannot delete your own tenant' });
  }

  const tenant = await getTenantById(c.env.DB, id);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  // Clean up infrastructure for pro/enterprise tenants
  const infraCleanup: string[] = [];
  if (tenant.slug && (tenant.tier === 'professional' || tenant.tier === 'enterprise')) {
    try {
      // Delete dedicated worker
      await deleteTenantWorker(tenant.slug, c.env);
      infraCleanup.push('worker');
    } catch (err) {
      console.error(`Failed to delete worker for tenant ${tenant.slug}:`, err);
      // Continue with deletion even if worker cleanup fails
    }

    try {
      // Stop sandbox/container
      await stopAgentContainer(tenant.slug, c.env);
      infraCleanup.push('sandbox');
    } catch (err) {
      console.error(`Failed to stop sandbox for tenant ${tenant.slug}:`, err);
    }
  }

  // Delete tenant from database
  await deleteTenant(c.env.DB, id);

  return c.json({
    message: 'Tenant deleted',
    infrastructure_cleaned: infraCleanup,
  });
});

// ============================================================
// Tenant-scoped user routes: /admin/tenants/:tenantId/users
// ============================================================

// Transform user to API response format expected by admin frontend
function toUserResponse(user: { id: string; email: string; tenantId: string | null; roles: string[]; enabled: boolean; createdAt: string; updatedAt: string }) {
  return {
    user_id: user.id,
    email: user.email,
    email_verified: true, // We don't have email verification yet, default to true
    roles: user.roles,
    enabled: user.enabled,
    created_at: Math.floor(new Date(user.createdAt).getTime() / 1000),
    updated_at: Math.floor(new Date(user.updatedAt).getTime() / 1000),
  };
}

// List users for a tenant
app.get('/:tenantId/users', zValidator('query', paginationSchema), async (c) => {
  const tenantId = c.req.param('tenantId');
  const { offset, limit } = c.req.valid('query');

  // Verify tenant exists
  const tenant = await getTenantById(c.env.DB, tenantId);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  const result = await listUsers(c.env.DB, tenantId, offset, limit);

  // Transform to API response format
  const users = result.users.map(({ passwordHash, ...user }) => toUserResponse(user));

  return c.json({
    users,
    total: result.total,
    offset,
    limit,
  });
});

// Get single user in a tenant
app.get('/:tenantId/users/:userId', async (c) => {
  const tenantId = c.req.param('tenantId');
  const userId = c.req.param('userId');

  const user = await getUserById(c.env.DB, userId);

  if (!user || user.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'User not found' });
  }

  const { passwordHash, ...userWithoutPassword } = user;
  return c.json(toUserResponse(userWithoutPassword));
});

// Create user in a tenant
app.post('/:tenantId/users', zValidator('json', createUserSchema), async (c) => {
  const tenantId = c.req.param('tenantId');
  const { email, password, roles } = c.req.valid('json');

  // Verify tenant exists
  const tenant = await getTenantById(c.env.DB, tenantId);
  if (!tenant) {
    throw new HTTPException(404, { message: 'Tenant not found' });
  }

  // Check if user already exists
  const existingUser = await getUserByEmail(c.env.DB, email, tenantId);
  if (existingUser) {
    throw new HTTPException(409, { message: 'User already exists' });
  }

  // Hash password
  const passwordHash = await hashPassword(password);

  // Create user
  const user = await createUser(c.env.DB, {
    id: crypto.randomUUID(),
    email,
    tenantId,
    roles,
    passwordHash,
    enabled: true,
  });

  const { passwordHash: _, ...userWithoutPassword } = user;
  return c.json(userWithoutPassword, 201);
});

// Update user in a tenant
app.patch('/:tenantId/users/:userId', zValidator('json', updateUserSchema), async (c) => {
  const tenantId = c.req.param('tenantId');
  const userId = c.req.param('userId');
  const updates = c.req.valid('json');

  const user = await getUserById(c.env.DB, userId);
  if (!user || user.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'User not found' });
  }

  // Hash new password if provided
  let passwordHash: string | undefined;
  if (updates.password) {
    passwordHash = await hashPassword(updates.password);
  }

  await updateUser(c.env.DB, userId, {
    email: updates.email,
    roles: updates.roles,
    passwordHash,
    enabled: updates.enabled,
  });

  const updatedUser = await getUserById(c.env.DB, userId);
  const { passwordHash: _, ...userWithoutPassword } = updatedUser!;
  return c.json(userWithoutPassword);
});

// Delete user in a tenant
app.delete('/:tenantId/users/:userId', async (c) => {
  const tenantId = c.req.param('tenantId');
  const userId = c.req.param('userId');
  const currentUserId = c.get('userId');

  // Prevent self-deletion
  if (userId === currentUserId) {
    throw new HTTPException(400, { message: 'Cannot delete yourself' });
  }

  const user = await getUserById(c.env.DB, userId);
  if (!user || user.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'User not found' });
  }

  // Clean up user data and connector tokens
  await Promise.all([
    deleteUser(c.env.DB, userId),
    deleteAllUserTokens(c.env.KV, tenantId, userId),
  ]);

  return c.json({ message: 'User deleted' });
});

export { app as tenantsRoute };
