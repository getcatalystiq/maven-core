/**
 * Chat route handlers
 */

import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { chatRequestSchema } from '@maven/shared';
import { chatSync } from '../agent';

/**
 * Safely parse roles from header, returning default if invalid
 */
function safeParseRoles(header: string | undefined): string[] {
  if (!header) return ['user'];
  try {
    const parsed = JSON.parse(header);
    if (Array.isArray(parsed) && parsed.every((r) => typeof r === 'string')) {
      return parsed;
    }
    return ['user'];
  } catch {
    return ['user'];
  }
}

const app = new Hono();

app.post(
  '/',
  zValidator('json', chatRequestSchema),
  async (c) => {
    const t0 = Date.now();
    const { message, sessionId, skills } = c.req.valid('json');

    // Get context from headers (tenant required)
    const tenantId = c.req.header('X-Tenant-Id');
    if (!tenantId) {
      return c.json({ error: 'X-Tenant-Id header is required' }, 400);
    }
    const userId = c.req.header('X-User-Id') || 'anonymous';
    const userRoles = safeParseRoles(c.req.header('X-User-Roles'));

    console.log(`[AGENT TIMING] T+0ms: Agent received chat request`);

    try {
      // Log environment for debugging
      console.log(`[AGENT TIMING] T+${Date.now() - t0}ms: Environment check`, {
        CLAUDE_CODE_USE_BEDROCK: process.env.CLAUDE_CODE_USE_BEDROCK,
        AWS_ACCESS_KEY_ID: process.env.AWS_ACCESS_KEY_ID ? 'set' : 'not set',
        AWS_REGION: process.env.AWS_REGION,
        ANTHROPIC_MODEL: process.env.ANTHROPIC_MODEL,
      });

      console.log(`[AGENT TIMING] T+${Date.now() - t0}ms: Calling chatSync (Claude SDK)`);
      const result = await chatSync(message, {
        sessionId,
        tenantId,
        userId,
        userRoles,
        skills,
      });
      console.log(`[AGENT TIMING] T+${Date.now() - t0}ms: chatSync completed`);

      return c.json({
        response: result.response,
        sessionId: result.sessionId,
        usage: result.usage,
        timing: result.timing,
      });
    } catch (error) {
      console.error('Chat error:', error);
      // Include full error details for debugging
      const errorObj = error as Error & { cause?: unknown; code?: string; stderr?: string };
      return c.json(
        {
          error: 'Chat processing failed',
          message: errorObj.message,
          stack: errorObj.stack,
          cause: errorObj.cause,
          code: errorObj.code,
        },
        500
      );
    }
  }
);

export { app as chatRoute };
