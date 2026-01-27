/**
 * Authentication middleware
 */

import { createMiddleware } from 'hono/factory';
import { HTTPException } from 'hono/http-exception';
import { verifyToken, getSecret } from '@maven/shared';
import type { Env, Variables } from '../index';

/**
 * JWT authentication middleware
 * Validates Bearer token and sets user context
 */
export const jwtAuth = createMiddleware<{ Bindings: Env; Variables: Variables }>(
  async (c, next) => {
    const authHeader = c.req.header('Authorization');

    if (!authHeader?.startsWith('Bearer ')) {
      throw new HTTPException(401, { message: 'Missing or invalid Authorization header' });
    }

    const token = authHeader.slice(7);

    try {
      const publicKey = await getSecret(c.env.JWT_PUBLIC_KEY);
      const payload = await verifyToken(
        token,
        publicKey,
        c.env.JWT_ISSUER
      );

      // Set user context
      c.set('userId', payload.sub);
      // tenant_id can be null for super-admins
      c.set('tenantId', payload.tenant_id ?? '');
      c.set('roles', payload.roles);

      await next();
    } catch (error) {
      console.error('JWT verification failed:', error);
      throw new HTTPException(401, { message: 'Invalid or expired token' });
    }
  }
);

/**
 * Admin authorization middleware
 * Requires 'admin' or 'super-admin' role
 * Super-admin can access any tenant's resources
 */
export const adminAuth = createMiddleware<{ Bindings: Env; Variables: Variables }>(
  async (c, next) => {
    const roles = c.get('roles') || [];

    const isAdmin = roles.includes('admin');
    // Accept both hyphenated and underscored versions for super-admin
    const isSuperAdmin = roles.includes('super-admin') || roles.includes('super_admin');

    if (!isAdmin && !isSuperAdmin) {
      throw new HTTPException(403, { message: 'Admin access required' });
    }

    // Super-admin can override tenant from query param or header
    if (isSuperAdmin) {
      c.set('isSuperAdmin', true);
      const overrideTenant = c.req.query('tenantId') || c.req.header('X-Tenant-Id');
      if (overrideTenant) {
        c.set('tenantId', overrideTenant);
      }
    }

    await next();
  }
);

/**
 * Internal API authentication middleware
 * For sandbox-to-controller communication
 */
export const internalAuth = createMiddleware<{ Bindings: Env }>(async (c, next) => {
  const apiKey = c.req.header('X-Internal-Key');
  const internalKey = await getSecret(c.env.INTERNAL_API_KEY);

  if (!apiKey || apiKey !== internalKey) {
    throw new HTTPException(401, { message: 'Invalid internal API key' });
  }

  await next();
});

