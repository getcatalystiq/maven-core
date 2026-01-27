/**
 * Maven Control Plane - Cloudflare Worker Entry Point
 *
 * This is the control plane that handles:
 * - Authentication (JWT issue/validate)
 * - Admin endpoints (users, tenants, roles, skills, connectors)
 * - OAuth flows for connectors
 * - Internal API for tenant workers to fetch config
 *
 * Note: Chat routing is handled by the separate tenant-worker package.
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { secureHeaders } from 'hono/secure-headers';
import { HTTPException } from 'hono/http-exception';
import type { Secret } from '@maven/shared';
import { authRoutes } from './routes/auth';
import { adminRoutes } from './routes/admin';
import { oauthRoutes } from './routes/oauth';
import { internalRoutes } from './routes/internal';
import { jwtAuth, adminAuth, internalAuth } from './middleware/auth';
import { rateLimitMiddleware } from './middleware/ratelimit';
import { jwksHandler } from './routes/auth/jwks';

// Environment bindings type
export interface Env {
  // Storage
  DB: D1Database;
  KV: KVNamespace;
  FILES: R2Bucket;

  // Configuration
  JWT_ISSUER: string;
  JWT_KEY_ID: string;

  // Secrets (Secrets Store in production, plain strings in local dev)
  // @see https://developers.cloudflare.com/secrets-store/
  JWT_PRIVATE_KEY: Secret;
  JWT_PUBLIC_KEY: Secret;
  INTERNAL_API_KEY: Secret;

  // CORS configuration (comma-separated list of allowed origins, or '*' for all)
  CORS_ALLOWED_ORIGINS?: string;

  // Cloudflare API credentials (for tenant provisioning)
  // These are Secret types to support both Secrets Store (production) and plain strings (local dev)
  CF_ACCOUNT_ID?: Secret;
  CF_API_TOKEN?: Secret;

  // Agent container configuration
  AGENT_IMAGE_TAG?: string; // e.g., "v1.0.0", "v1.5.0", "latest" - defaults to v1.0.0
}

// Context variables type - exported for use in routes and middleware
export type Variables = {
  userId: string;
  tenantId: string;
  roles: string[];
  isSuperAdmin?: boolean;
};

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// Global middleware
app.use('*', logger());
app.use('*', secureHeaders());

// CORS middleware with configurable origins
app.use('*', async (c, next) => {
  const allowedOriginsStr = c.env.CORS_ALLOWED_ORIGINS || '';
  const requestOrigin = c.req.header('Origin') || '*';

  // Parse allowed origins
  let origin: string | string[] | ((origin: string) => string | undefined | null);
  let allowCredentials = false;

  if (!allowedOriginsStr || allowedOriginsStr === '*') {
    // When no specific origins configured, reflect the request origin to allow credentials
    origin = requestOrigin;
    allowCredentials = true;
  } else {
    // Parse comma-separated list of origins
    const allowedOrigins = allowedOriginsStr.split(',').map((o) => o.trim()).filter(Boolean);

    // Create validator function
    origin = (reqOrigin: string) => {
      if (allowedOrigins.includes(reqOrigin)) {
        return reqOrigin;
      }
      return null;
    };
    allowCredentials = true;
  }

  const corsMiddleware = cors({
    origin,
    allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
    allowHeaders: ['Content-Type', 'Authorization', 'X-Tenant-Id', 'X-Internal-Key'],
    exposeHeaders: ['X-Request-Id', 'X-RateLimit-Limit', 'X-RateLimit-Remaining', 'X-RateLimit-Reset'],
    maxAge: 86400,
    credentials: allowCredentials,
  });

  return corsMiddleware(c, next);
});

// Health check
app.get('/health', (c) => c.json({ status: 'ok', timestamp: new Date().toISOString() }));

// JWKS endpoint (public)
app.get('/.well-known/jwks.json', jwksHandler);

// Auth routes (public)
app.route('/auth', authRoutes);

// OAuth routes (mix of public callbacks and authenticated)
app.route('/oauth', oauthRoutes);

// Admin routes (admin auth required)
app.use('/admin/*', jwtAuth, adminAuth, rateLimitMiddleware);
app.route('/admin', adminRoutes);

// Internal routes (for tenant-worker/sandbox to fetch config)
app.use('/internal/*', internalAuth);
app.route('/internal', internalRoutes);

// 404 handler
app.notFound((c) => {
  return c.json({ error: 'Not Found', path: c.req.path }, 404);
});

// Error handler
app.onError((err, c) => {
  // Handle HTTPException properly (return the intended status code)
  if (err instanceof HTTPException) {
    return c.json(
      {
        error: err.message,
      },
      err.status
    );
  }

  // Log unexpected errors
  console.error('Unhandled error:', err);
  return c.json(
    {
      error: 'Internal Server Error',
    },
    500
  );
});

export default app;
