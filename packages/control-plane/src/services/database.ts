/**
 * D1 Database service
 */

import type { User, Tenant, Role, Skill, Connector } from '@maven/shared';

// User operations
export async function createUser(
  db: D1Database,
  user: Omit<User, 'createdAt' | 'updatedAt'>
): Promise<User> {
  const now = new Date().toISOString();

  await db
    .prepare(
      `INSERT INTO users (id, email, tenant_id, roles, password_hash, enabled, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .bind(
      user.id,
      user.email,
      user.tenantId,
      JSON.stringify(user.roles),
      user.passwordHash || null,
      user.enabled ? 1 : 0,
      now,
      now
    )
    .run();

  return { ...user, createdAt: now, updatedAt: now };
}

export async function getUserById(db: D1Database, id: string): Promise<User | null> {
  const row = await db
    .prepare('SELECT * FROM users WHERE id = ?')
    .bind(id)
    .first<UserRow>();

  return row ? rowToUser(row) : null;
}

export async function getUserByEmail(
  db: D1Database,
  email: string,
  tenantId: string
): Promise<User | null> {
  const row = await db
    .prepare('SELECT * FROM users WHERE email = ? AND tenant_id = ?')
    .bind(email, tenantId)
    .first<UserRow>();

  return row ? rowToUser(row) : null;
}

export async function getSuperAdminByEmail(
  db: D1Database,
  email: string
): Promise<User | null> {
  // Super-admins have no tenant (tenant_id IS NULL)
  const row = await db
    .prepare('SELECT * FROM users WHERE email = ? AND tenant_id IS NULL')
    .bind(email)
    .first<UserRow>();

  return row ? rowToUser(row) : null;
}

export async function listUsers(
  db: D1Database,
  tenantId: string,
  offset = 0,
  limit = 20
): Promise<{ users: User[]; total: number }> {
  const [usersResult, countResult] = await Promise.all([
    db
      .prepare('SELECT * FROM users WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?')
      .bind(tenantId, limit, offset)
      .all<UserRow>(),
    db
      .prepare('SELECT COUNT(*) as count FROM users WHERE tenant_id = ?')
      .bind(tenantId)
      .first<{ count: number }>(),
  ]);

  return {
    users: usersResult.results.map(rowToUser),
    total: countResult?.count || 0,
  };
}

export async function updateUser(
  db: D1Database,
  id: string,
  updates: Partial<Pick<User, 'email' | 'roles' | 'passwordHash' | 'enabled'>>
): Promise<void> {
  const setClauses: string[] = ['updated_at = ?'];
  const values: (string | number)[] = [new Date().toISOString()];

  if (updates.email !== undefined) {
    setClauses.push('email = ?');
    values.push(updates.email);
  }
  if (updates.roles !== undefined) {
    setClauses.push('roles = ?');
    values.push(JSON.stringify(updates.roles));
  }
  if (updates.passwordHash !== undefined) {
    setClauses.push('password_hash = ?');
    values.push(updates.passwordHash);
  }
  if (updates.enabled !== undefined) {
    setClauses.push('enabled = ?');
    values.push(updates.enabled ? 1 : 0);
  }

  values.push(id);

  await db
    .prepare(`UPDATE users SET ${setClauses.join(', ')} WHERE id = ?`)
    .bind(...values)
    .run();
}

export async function deleteUser(db: D1Database, id: string): Promise<void> {
  await db.prepare('DELETE FROM users WHERE id = ?').bind(id).run();
}

// Tenant operations
export async function createTenant(
  db: D1Database,
  tenant: Omit<Tenant, 'createdAt' | 'updatedAt'>
): Promise<Tenant> {
  const now = new Date().toISOString();

  await db
    .prepare(
      `INSERT INTO tenants (id, name, slug, tier, enabled, settings, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .bind(
      tenant.id,
      tenant.name,
      tenant.slug,
      tenant.tier,
      tenant.enabled ? 1 : 0,
      JSON.stringify(tenant.settings),
      now,
      now
    )
    .run();

  return { ...tenant, createdAt: now, updatedAt: now };
}

export async function getTenantById(db: D1Database, id: string): Promise<Tenant | null> {
  const row = await db
    .prepare('SELECT * FROM tenants WHERE id = ?')
    .bind(id)
    .first<TenantRow>();

  return row ? rowToTenant(row) : null;
}

export async function getTenantBySlug(db: D1Database, slug: string): Promise<Tenant | null> {
  const row = await db
    .prepare('SELECT * FROM tenants WHERE slug = ?')
    .bind(slug)
    .first<TenantRow>();

  return row ? rowToTenant(row) : null;
}

export async function listTenants(
  db: D1Database,
  offset = 0,
  limit = 20
): Promise<{ tenants: Tenant[]; total: number }> {
  const [tenantsResult, countResult] = await Promise.all([
    db
      .prepare('SELECT * FROM tenants ORDER BY created_at DESC LIMIT ? OFFSET ?')
      .bind(limit, offset)
      .all<TenantRow>(),
    db.prepare('SELECT COUNT(*) as count FROM tenants').first<{ count: number }>(),
  ]);

  return {
    tenants: tenantsResult.results.map(rowToTenant),
    total: countResult?.count || 0,
  };
}

export async function updateTenant(
  db: D1Database,
  id: string,
  updates: Partial<Pick<Tenant, 'name' | 'tier' | 'enabled' | 'settings'>>
): Promise<void> {
  const setClauses: string[] = ['updated_at = ?'];
  const values: (string | number)[] = [new Date().toISOString()];

  if (updates.name !== undefined) {
    setClauses.push('name = ?');
    values.push(updates.name);
  }
  if (updates.tier !== undefined) {
    setClauses.push('tier = ?');
    values.push(updates.tier);
  }
  if (updates.enabled !== undefined) {
    setClauses.push('enabled = ?');
    values.push(updates.enabled ? 1 : 0);
  }
  if (updates.settings !== undefined) {
    setClauses.push('settings = ?');
    values.push(JSON.stringify(updates.settings));
  }

  values.push(id);

  await db
    .prepare(`UPDATE tenants SET ${setClauses.join(', ')} WHERE id = ?`)
    .bind(...values)
    .run();
}

export async function deleteTenant(db: D1Database, id: string): Promise<void> {
  await db.prepare('DELETE FROM tenants WHERE id = ?').bind(id).run();
}

// Session operations
export interface SessionRow {
  id: string;
  tenant_id: string;
  user_id: string;
  status: string;
  metadata: string;
  created_at: string;
  updated_at: string;
}

export interface Session {
  id: string;
  tenantId: string;
  userId: string;
  status: string;
  metadata: {
    title?: string;
    lastMessage?: string;
    messageCount?: number;
    totalInputTokens?: number;
    totalOutputTokens?: number;
  };
  createdAt: string;
  updatedAt: string;
}

function rowToSession(row: SessionRow): Session {
  return {
    id: row.id,
    tenantId: row.tenant_id,
    userId: row.user_id,
    status: row.status,
    metadata: JSON.parse(row.metadata || '{}'),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export async function listSessionsForUser(
  db: D1Database,
  tenantId: string,
  userId: string,
  limit = 50
): Promise<Session[]> {
  const result = await db
    .prepare(
      `SELECT * FROM sessions
       WHERE tenant_id = ? AND user_id = ?
       ORDER BY updated_at DESC
       LIMIT ?`
    )
    .bind(tenantId, userId, limit)
    .all<SessionRow>();

  return result.results.map(rowToSession);
}

export async function upsertSession(
  db: D1Database,
  session: {
    id: string;
    tenantId: string;
    userId: string;
    status?: string;
    metadata?: Session['metadata'];
  }
): Promise<void> {
  const now = new Date().toISOString();
  const metadata = JSON.stringify(session.metadata || {});

  await db
    .prepare(
      `INSERT INTO sessions (id, tenant_id, user_id, status, metadata, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET
         status = excluded.status,
         metadata = excluded.metadata,
         updated_at = excluded.updated_at`
    )
    .bind(
      session.id,
      session.tenantId,
      session.userId,
      session.status || 'active',
      metadata,
      now,
      now
    )
    .run();
}

export async function getSession(
  db: D1Database,
  sessionId: string,
  tenantId: string
): Promise<Session | null> {
  const row = await db
    .prepare('SELECT * FROM sessions WHERE id = ? AND tenant_id = ?')
    .bind(sessionId, tenantId)
    .first<SessionRow>();

  return row ? rowToSession(row) : null;
}

// Row types and converters
interface UserRow {
  id: string;
  email: string;
  tenant_id: string | null;  // Null for super-admins
  roles: string;
  password_hash: string | null;
  enabled: number;
  created_at: string;
  updated_at: string;
}

interface TenantRow {
  id: string;
  name: string;
  slug: string;
  tier: string;
  enabled: number;
  settings: string;
  created_at: string;
  updated_at: string;
}

function rowToUser(row: UserRow): User {
  return {
    id: row.id,
    email: row.email,
    tenantId: row.tenant_id,
    roles: JSON.parse(row.roles),
    passwordHash: row.password_hash || undefined,
    enabled: row.enabled === 1,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function rowToTenant(row: TenantRow): Tenant {
  return {
    id: row.id,
    name: row.name,
    slug: row.slug,
    tier: row.tier as Tenant['tier'],
    enabled: row.enabled === 1,
    settings: JSON.parse(row.settings),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}
