/**
 * JWT Authentication Middleware for Tenant Worker
 *
 * Validates Bearer tokens using the public key.
 * This is stateless - no database calls needed.
 */

import { createMiddleware } from 'hono/factory';
import { HTTPException } from 'hono/http-exception';
import { verifyToken, getSecret } from '@maven/shared';
import type { Env, Variables } from '../index';

/**
 * JWT authentication middleware
 * Validates Bearer token and sets user context from token claims
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

      // Tenant worker requires a tenant context
      // Super-admins (tenant_id = null) must use Control Plane instead
      if (!payload.tenant_id) {
        throw new HTTPException(403, {
          message: 'Tenant worker requires a tenant-scoped token. Super-admin access should use Control Plane API.',
        });
      }

      // Set user context from token claims
      c.set('userId', payload.sub);
      c.set('tenantId', payload.tenant_id);
      c.set('roles', payload.roles);

      await next();
    } catch (error) {
      console.error('JWT verification failed:', error);
      throw new HTTPException(401, { message: 'Invalid or expired token' });
    }
  }
);
