/**
 * Registration endpoint
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import {
  registerRequestSchema,
  hashPassword,
  createTokenPair,
  getSecret,
} from '@maven/shared';
import { createUser, getUserByEmail, getTenantById } from '../../services/database';
import type { Env } from '../../index';

const app = new Hono<{ Bindings: Env }>();

app.post(
  '/',
  zValidator('json', registerRequestSchema),
  async (c) => {
    const { email, password, tenantId: requestedTenantId } = c.req.valid('json');

    // Tenant must be explicitly provided
    if (!requestedTenantId) {
      throw new HTTPException(400, { message: 'Tenant ID is required' });
    }

    const tenantId = requestedTenantId;

    // Check if tenant exists
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

    // Create user with no roles - admin must assign roles
    const userId = crypto.randomUUID();
    const user = await createUser(c.env.DB, {
      id: userId,
      email,
      tenantId,
      roles: [],
      passwordHash,
      enabled: true,
    });

    // Generate tokens
    const privateKey = await getSecret(c.env.JWT_PRIVATE_KEY);
    const tokens = await createTokenPair(
      user.id,
      user.tenantId,
      user.roles,
      privateKey,
      c.env.JWT_KEY_ID,
      c.env.JWT_ISSUER
    );

    return c.json(
      {
        access_token: tokens.accessToken,
        refresh_token: tokens.refreshToken,
        expires_in: tokens.expiresIn,
        token_type: 'Bearer',
        user: {
          id: user.id,
          email: user.email,
          tenantId: user.tenantId,
          roles: user.roles,
        },
      },
      201
    );
  }
);

export { app as registerRoute };
