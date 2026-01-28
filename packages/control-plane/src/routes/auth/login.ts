/**
 * Login endpoint
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import { loginRequestSchema, verifyPassword, createTokenPair, getSecret } from '@maven/shared';
import { getUserByEmail, getSuperAdminByEmail } from '../../services/database';
import type { Env } from '../../index';

const app = new Hono<{ Bindings: Env }>();

app.post(
  '/',
  zValidator('json', loginRequestSchema),
  async (c) => {
    const { email, password } = c.req.valid('json');

    // First, check if this is a super-admin (tenant-less user)
    let user = await getSuperAdminByEmail(c.env.DB, email);

    // If not a super-admin, look up by tenant (tenant header required)
    if (!user) {
      const tenantId = c.req.header('X-Tenant-Id');
      if (!tenantId) {
        throw new HTTPException(400, { message: 'X-Tenant-Id header is required' });
      }
      user = await getUserByEmail(c.env.DB, email, tenantId);
    }

    if (!user) {
      throw new HTTPException(401, { message: 'Invalid credentials' });
    }

    // Check if user is enabled
    if (!user.enabled) {
      throw new HTTPException(403, { message: 'Account is disabled' });
    }

    // Verify password
    if (!user.passwordHash) {
      throw new HTTPException(401, { message: 'Invalid credentials' });
    }

    const isValid = await verifyPassword(password, user.passwordHash);
    if (!isValid) {
      throw new HTTPException(401, { message: 'Invalid credentials' });
    }

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

    return c.json({
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
    });
  }
);

export { app as loginRoute };
