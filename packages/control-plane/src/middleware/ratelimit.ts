/**
 * Rate limiting middleware using sliding window algorithm
 */

import { createMiddleware } from 'hono/factory';
import { HTTPException } from 'hono/http-exception';
import type { Context } from 'hono';
import type { Env, Variables } from '../index';
import { TIER_LIMITS } from '@maven/shared';

const WINDOW_SIZE_MS = 60 * 1000; // 1 minute

interface RateLimitWindow {
  count: number;
  windowStart: number;
}

interface RateLimitConfig {
  keyPrefix: string;
  getKey: (c: Context) => string | null;
  getMaxRequests: (c: Context) => number | Promise<number>;
  errorMessage?: string;
}

/**
 * Create a rate limiting middleware with custom configuration
 */
function createRateLimiter<E extends { Bindings: Env }>(config: RateLimitConfig) {
  return createMiddleware<E>(async (c, next) => {
    const keyPart = config.getKey(c as unknown as Context);
    if (!keyPart) {
      await next();
      return;
    }

    const key = `${config.keyPrefix}:${keyPart}`;
    const now = Date.now();
    const maxRequests = await config.getMaxRequests(c as unknown as Context);

    // Get current window data
    const windowData = await c.env.KV.get<RateLimitWindow>(key, 'json');

    if (!windowData) {
      // First request in window
      await c.env.KV.put(
        key,
        JSON.stringify({ count: 1, windowStart: now }),
        { expirationTtl: 120 } // 2 minute TTL
      );
      setRateLimitHeaders(c, maxRequests, maxRequests - 1, now + WINDOW_SIZE_MS);
      await next();
      return;
    }

    // Check if we're in a new window
    if (now - windowData.windowStart > WINDOW_SIZE_MS) {
      // New window
      await c.env.KV.put(
        key,
        JSON.stringify({ count: 1, windowStart: now }),
        { expirationTtl: 120 }
      );
      setRateLimitHeaders(c, maxRequests, maxRequests - 1, now + WINDOW_SIZE_MS);
      await next();
      return;
    }

    // Check rate limit
    if (windowData.count >= maxRequests) {
      const retryAfter = Math.ceil((windowData.windowStart + WINDOW_SIZE_MS - now) / 1000);
      const resetTime = windowData.windowStart + WINDOW_SIZE_MS;

      c.header('Retry-After', String(retryAfter));
      setRateLimitHeaders(c, maxRequests, 0, resetTime);

      const message = config.errorMessage || `Rate limit exceeded. Try again in ${retryAfter} seconds.`;
      throw new HTTPException(429, { message });
    }

    // Increment counter
    await c.env.KV.put(
      key,
      JSON.stringify({ count: windowData.count + 1, windowStart: windowData.windowStart }),
      { expirationTtl: 120 }
    );

    // Set rate limit headers
    const resetTime = windowData.windowStart + WINDOW_SIZE_MS;
    setRateLimitHeaders(c, maxRequests, maxRequests - windowData.count - 1, resetTime);

    await next();
  });
}

function setRateLimitHeaders(c: Context, limit: number, remaining: number, resetMs: number) {
  c.header('X-RateLimit-Limit', String(limit));
  c.header('X-RateLimit-Remaining', String(remaining));
  c.header('X-RateLimit-Reset', String(Math.ceil(resetMs / 1000)));
}

/**
 * Get client IP from request headers
 */
function getClientIP(c: Context): string {
  // Cloudflare provides the client IP in CF-Connecting-IP
  const cfIP = c.req.header('CF-Connecting-IP');
  if (cfIP) return cfIP;

  // Fallback to X-Forwarded-For
  const xForwardedFor = c.req.header('X-Forwarded-For');
  if (xForwardedFor) {
    // Get the first IP in the chain
    return xForwardedFor.split(',')[0].trim();
  }

  // Fallback to X-Real-IP
  const xRealIP = c.req.header('X-Real-IP');
  if (xRealIP) return xRealIP;

  // Default fallback
  return 'unknown';
}

/**
 * Rate limiting middleware for authenticated requests
 * Uses user ID for rate limiting based on tenant tier
 */
export const rateLimitMiddleware = createRateLimiter<{ Bindings: Env; Variables: Variables }>({
  keyPrefix: 'ratelimit',
  getKey: (c) => {
    const tenantId = c.get('tenantId');
    const userId = c.get('userId');
    return tenantId && userId ? `${tenantId}:${userId}` : null;
  },
  getMaxRequests: async (c) => {
    const tenantId = c.get('tenantId');
    const tenant = await getTenant(c.env.DB, tenantId);
    const tierLimits = TIER_LIMITS[tenant?.tier || 'free'];
    return tierLimits.rateLimitPerMinute;
  },
});

/**
 * Rate limiting middleware for authentication endpoints
 * Uses IP-based limiting since we don't have user context
 */
const MAX_AUTH_ATTEMPTS = 10;

export const authRateLimitMiddleware = createRateLimiter<{ Bindings: Env }>({
  keyPrefix: 'auth-ratelimit',
  getKey: (c) => getClientIP(c),
  getMaxRequests: () => MAX_AUTH_ATTEMPTS,
  errorMessage: 'Too many authentication attempts. Please try again later.',
});

async function getTenant(db: D1Database, tenantId: string): Promise<{ tier: string } | null> {
  const result = await db
    .prepare('SELECT tier FROM tenants WHERE id = ?')
    .bind(tenantId)
    .first<{ tier: string }>();

  return result;
}
