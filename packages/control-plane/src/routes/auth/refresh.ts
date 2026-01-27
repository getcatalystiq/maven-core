/**
 * Token refresh endpoint
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import { refreshTokenRequestSchema, verifyToken, createTokenPair, getSecret, getSecrets } from '@maven/shared';
import { getUserById } from '../../services/database';
import type { Env } from '../../index';

const app = new Hono<{ Bindings: Env }>();

app.post(
  '/',
  zValidator('json', refreshTokenRequestSchema),
  async (c) => {
    const { refresh_token: refreshToken } = c.req.valid('json');

    try {
      // Get keys from Secrets Store
      const [publicKey, privateKey] = await getSecrets([
        c.env.JWT_PUBLIC_KEY,
        c.env.JWT_PRIVATE_KEY,
      ]);

      // Verify refresh token
      const payload = await verifyToken(
        refreshToken,
        publicKey,
        c.env.JWT_ISSUER
      );

      // Check token type
      if (payload.type !== 'refresh') {
        throw new HTTPException(401, { message: 'Invalid token type' });
      }

      // Get user
      const user = await getUserById(c.env.DB, payload.sub);
      if (!user) {
        throw new HTTPException(401, { message: 'User not found' });
      }

      // Check if user is enabled
      if (!user.enabled) {
        throw new HTTPException(403, { message: 'Account is disabled' });
      }

      // Generate new tokens
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
      });
    } catch (error) {
      if (error instanceof HTTPException) throw error;
      throw new HTTPException(401, { message: 'Invalid or expired refresh token' });
    }
  }
);

export { app as refreshRoute };
