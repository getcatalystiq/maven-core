/**
 * JWKS (JSON Web Key Set) endpoint
 */

import type { Context } from 'hono';
import { getJWKS, getSecret } from '@maven/shared';
import type { Env } from '../../index';

export async function jwksHandler(c: Context<{ Bindings: Env }>) {
  const publicKey = await getSecret(c.env.JWT_PUBLIC_KEY);
  const jwks = await getJWKS(publicKey, c.env.JWT_KEY_ID);

  return c.json(jwks, 200, {
    'Cache-Control': 'public, max-age=3600',
  });
}
