/**
 * Maven Tenant Worker - Lightweight Per-Tenant Chat Router
 *
 * This worker handles chat routing to tenant sandboxes via Durable Objects.
 * It's designed to be lightweight and deployable per-tenant if needed.
 *
 * Routes:
 * - /health - Health check
 * - /chat - Non-streaming chat
 * - /chat/stream - Streaming chat
 * - /sessions - Session management
 */

import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { secureHeaders } from 'hono/secure-headers';
import { jwtAuth } from './middleware/auth';
import { TenantAgent } from './durable-objects/tenant-agent';
import { Sandbox } from '@cloudflare/sandbox';

// Environment bindings type
export interface Env {
  // Durable Objects
  TENANT_AGENT: DurableObjectNamespace<TenantAgent>;

  // Sandbox SDK binding (for production - Cloudflare Sandbox)
  Sandbox: DurableObjectNamespace<Sandbox>;

  // JWT Configuration
  JWT_ISSUER: string;
  JWT_PUBLIC_KEY: string;

  // Control Plane URL for fetching config
  CONTROL_PLANE_URL: string;
  INTERNAL_API_KEY: string;

  // Claude/Anthropic configuration
  ANTHROPIC_API_KEY?: string;

  // AWS Bedrock configuration (alternative to Anthropic API)
  AWS_ACCESS_KEY_ID?: string;
  AWS_SECRET_ACCESS_KEY?: string;
  AWS_REGION?: string;
  AWS_SESSION_TOKEN?: string;

  // CORS configuration
  CORS_ALLOWED_ORIGINS?: string;

  // Agent URL for local development
  AGENT_URL?: string;

  // Sandbox configuration
  SANDBOX_SLEEP_AFTER?: string; // e.g., '10m', '30m', '1h' - default: '10m'
}

// Context variables type
export type Variables = {
  userId: string;
  tenantId: string;
  roles: string[];
};

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// Global middleware
app.use('*', logger());
app.use('*', secureHeaders());

// CORS middleware with configurable origins
app.use('*', async (c, next) => {
  const allowedOriginsStr = c.env.CORS_ALLOWED_ORIGINS || '';

  let origin: string | string[] | ((origin: string) => string | undefined | null);

  if (!allowedOriginsStr || allowedOriginsStr === '*') {
    origin = '*';
  } else {
    const allowedOrigins = allowedOriginsStr.split(',').map((o) => o.trim()).filter(Boolean);
    origin = (requestOrigin: string) => {
      if (allowedOrigins.includes(requestOrigin)) {
        return requestOrigin;
      }
      return null;
    };
  }

  const corsMiddleware = cors({
    origin,
    allowMethods: ['GET', 'POST', 'OPTIONS'],
    allowHeaders: ['Content-Type', 'Authorization', 'X-Tenant-Id'],
    exposeHeaders: ['X-Request-Id'],
    maxAge: 86400,
    credentials: allowedOriginsStr !== '*' && allowedOriginsStr !== '',
  });

  return corsMiddleware(c, next);
});

// Health check (public)
app.get('/health', (c) => c.json({ status: 'ok', timestamp: new Date().toISOString() }));

// All chat routes require JWT auth
app.use('/chat/*', jwtAuth);
app.use('/sessions/*', jwtAuth);

// Chat endpoint - proxy to Durable Object
app.post('/chat', async (c) => {
  const t0 = Date.now();
  const tenantId = c.get('tenantId');
  const userId = c.get('userId');
  const roles = c.get('roles');

  console.log(`[TIMING] T+${Date.now() - t0}ms: Worker received chat request, creating DO stub`);

  const agentId = c.env.TENANT_AGENT.idFromName(`tenant-${tenantId}`);
  const agent = c.env.TENANT_AGENT.get(agentId);

  console.log(`[TIMING] T+${Date.now() - t0}ms: DO stub created, preparing request`);

  const request = new Request(c.req.url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId,
      'X-Tenant-Id': tenantId,
      'X-User-Roles': JSON.stringify(roles),
      'X-Request-Start': t0.toString(),
    },
    body: c.req.raw.body,
  });

  console.log(`[TIMING] T+${Date.now() - t0}ms: Calling DO fetch`);
  const response = await agent.fetch(request);
  console.log(`[TIMING] T+${Date.now() - t0}ms: DO fetch returned`);

  return response;
});

// Streaming chat endpoint
app.post('/chat/stream', async (c) => {
  const t0 = Date.now();
  const tenantId = c.get('tenantId');
  const userId = c.get('userId');
  const roles = c.get('roles');

  console.log(`[TIMING] T+${Date.now() - t0}ms: Worker received stream request`);

  const agentId = c.env.TENANT_AGENT.idFromName(`tenant-${tenantId}`);
  const agent = c.env.TENANT_AGENT.get(agentId);

  const request = new Request(c.req.url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId,
      'X-Tenant-Id': tenantId,
      'X-User-Roles': JSON.stringify(roles),
      'X-Request-Start': t0.toString(),
    },
    body: c.req.raw.body,
  });

  console.log(`[TIMING] T+${Date.now() - t0}ms: Calling DO fetch for stream`);
  const response = await agent.fetch(request);
  console.log(`[TIMING] T+${Date.now() - t0}ms: DO fetch returned stream response`);

  return response;
});

// SageMaker-compatible invocations endpoint
app.post('/chat/invocations', async (c) => {
  const tenantId = c.get('tenantId');
  const userId = c.get('userId');
  const roles = c.get('roles');

  const agentId = c.env.TENANT_AGENT.idFromName(`tenant-${tenantId}`);
  const agent = c.env.TENANT_AGENT.get(agentId);

  const request = new Request(c.req.url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId,
      'X-Tenant-Id': tenantId,
      'X-User-Roles': JSON.stringify(roles),
    },
    body: c.req.raw.body,
  });

  return agent.fetch(request);
});

// Session listing
app.get('/sessions', async (c) => {
  const tenantId = c.get('tenantId');
  const agentId = c.env.TENANT_AGENT.idFromName(`tenant-${tenantId}`);
  const agent = c.env.TENANT_AGENT.get(agentId);
  return agent.fetch(c.req.raw);
});

// Get specific session
app.get('/sessions/:id', async (c) => {
  const tenantId = c.get('tenantId');
  const agentId = c.env.TENANT_AGENT.idFromName(`tenant-${tenantId}`);
  const agent = c.env.TENANT_AGENT.get(agentId);
  return agent.fetch(c.req.raw);
});

// 404 handler
app.notFound((c) => {
  return c.json({ error: 'Not Found', path: c.req.path }, 404);
});

// Error handler
app.onError((err, c) => {
  console.error('Unhandled error:', err);
  return c.json(
    {
      error: 'Internal Server Error',
      message: err.message,
    },
    500
  );
});

export default app;
export { TenantAgent, Sandbox };
