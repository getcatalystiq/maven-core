/**
 * Maven Agent - Bun HTTP Server
 *
 * This server runs inside a Cloudflare Sandbox container and handles
 * chat requests using the Claude Agent SDK via HTTP streaming.
 */

// Initialize structured logger before anything else
// Note: The DO pulls logs from the container's log file using the pull model
// The logger here captures console output for structured formatting
import { initLogger, shutdownLogger } from './logging';

const tenantId = Bun.env.TENANT_ID || '';

initLogger({
  tenantId,
  maxBatchSize: 50,
  flushIntervalMs: 5000,
  passthrough: true, // Always show in stdout - DO reads from log file
});

// Import agent to trigger backend auto-detection before logging
import './agent';

import { Hono } from 'hono';
import { logger } from 'hono/logger';
import { cors } from 'hono/cors';
import { streamRoute } from './routes/stream';
import { sessionsRoute } from './routes/sessions';

const app = new Hono();

// Middleware
app.use('*', logger());
app.use('*', cors());

// Health check with debug info
app.get('/health', (c) => {
  return c.json({
    status: 'ok',
    runtime: 'bun',
    timestamp: new Date().toISOString(),
    tenantId: Bun.env.TENANT_ID || 'unknown',
    debug: {
      backend: Bun.env.CLAUDE_CODE_USE_BEDROCK === '1' ? 'bedrock' : 'anthropic',
      model: Bun.env.ANTHROPIC_MODEL || 'default',
      awsRegion: Bun.env.AWS_REGION || 'not set',
      hasAwsKey: !!Bun.env.AWS_ACCESS_KEY_ID,
      hasAwsSecret: !!Bun.env.AWS_SECRET_ACCESS_KEY,
      hasAnthropicKey: !!Bun.env.ANTHROPIC_API_KEY,
    },
  });
});

// Routes
app.route('/chat/stream', streamRoute);
app.route('/sessions', sessionsRoute);

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

// Start Bun HTTP server
const port = parseInt(Bun.env.PORT || '8080', 10);
const hostname = Bun.env.NODE_ENV === 'production' ? '0.0.0.0' : 'localhost';

console.log(`Starting Maven Agent on port ${port}...`);
console.log(`Tenant ID: ${Bun.env.TENANT_ID || 'not set'}`);
console.log(`Skills Path: ${Bun.env.SKILLS_PATH || '/app/skills'}`);
console.log(`Backend: ${Bun.env.CLAUDE_CODE_USE_BEDROCK === '1' ? 'AWS Bedrock' : 'Anthropic API'}`);
console.log(`Model: ${Bun.env.ANTHROPIC_MODEL || 'us.anthropic.claude-opus-4-5-20251101-v1:0'}`);
if (Bun.env.CLAUDE_CODE_USE_BEDROCK === '1') {
  console.log(`AWS Region: ${Bun.env.AWS_REGION || 'not set'}`);
}

const server = Bun.serve({
  port,
  hostname,
  fetch: app.fetch,
});

console.log(`Maven Agent listening on http://${hostname}:${port} (Bun runtime)`);

// Graceful shutdown handler
const shutdown = async (signal: string) => {
  console.log(`[Agent] ${signal} received, shutting down`);

  // Flush any remaining logs before exit
  await shutdownLogger();

  // Brief drain period
  await new Promise(r => setTimeout(r, 500));
  process.exit(0);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
