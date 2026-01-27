/**
 * Maven Agent - Bun HTTP Server with Native WebSocket
 *
 * This server runs inside a Cloudflare Sandbox container and handles
 * chat requests using the Claude Agent SDK.
 *
 * Uses Bun's native WebSocket for real-time streaming (7x faster than Node.js + ws).
 */

// Initialize structured logger before anything else
// Note: The DO pulls logs from the container's log file using the pull model
// The logger here captures console output for structured formatting
import { initLogger, shutdownLogger, getLogger } from './logging';

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
import { chatRoute } from './routes/chat';
import { streamRoute } from './routes/stream';
import { sessionsRoute } from './routes/sessions';
import { chat } from './agent';

// WebSocket connection data type
interface WebSocketData {
  tenantId: string;
  userId: string;
}

// Track active connections for graceful shutdown
const activeConnections = new Set<import('bun').ServerWebSocket<WebSocketData>>();

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
app.route('/chat', chatRoute);
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

// Start Bun server with native WebSocket support
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

const server = Bun.serve<WebSocketData>({
  port,
  hostname,

  fetch(req, server) {
    const url = new URL(req.url);

    // Handle WebSocket upgrade for /ws/chat
    if (url.pathname === '/ws/chat') {
      const tenantId = req.headers.get('x-tenant-id');
      const userId = req.headers.get('x-user-id') || 'anonymous';

      if (!tenantId) {
        return new Response('Missing X-Tenant-Id header', { status: 400 });
      }

      console.log(`[WS] Upgrade request received (tenant: ${tenantId}, user: ${userId})`);

      const upgraded = server.upgrade(req, {
        data: { tenantId, userId },
      });

      if (upgraded) {
        // Bun handles the response for successful upgrades
        return undefined as unknown as Response;
      }

      return new Response('WebSocket upgrade failed', { status: 400 });
    }

    // Handle all other requests via Hono
    return app.fetch(req);
  },

  websocket: {
    open(ws) {
      activeConnections.add(ws);
      const { tenantId, userId } = ws.data;
      console.log(`[WS] Connection opened (tenant: ${tenantId}, user: ${userId}, total: ${activeConnections.size})`);
    },

    async message(ws, message) {
      const { tenantId, userId } = ws.data;
      const t0 = Date.now();
      const t = () => Date.now() - t0;

      // Set session context for structured logging
      const logger = getLogger();
      logger.configure({ tenantId });

      console.log(`[WS] T+${t()}ms: Message received`);

      try {
        const payload = JSON.parse(
          typeof message === 'string' ? message : message.toString()
        ) as { message: string; sessionId?: string };

        const sessionId = payload.sessionId || crypto.randomUUID();
        console.log(`[WS] T+${t()}ms: Processing message, sessionId: ${sessionId}`);

        // IMMEDIATELY send start event to reduce TTFB
        // This ensures the client receives data right away while we wait for Claude
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'start', sessionId }) + '\n');
          console.log(`[WS] T+${t()}ms: Sent immediate start event`);
        }

        let firstMessage = true;
        let actualSessionId = sessionId;

        // Stream chat response directly to WebSocket
        // Use same format as HTTP stream for client compatibility
        for await (const msg of chat(payload.message, { sessionId, tenantId, userId })) {
          if (firstMessage) {
            console.log(`[WS] T+${t()}ms: First message from SDK (type: ${msg.type})`);
            firstMessage = false;
          }

          if (ws.readyState !== WebSocket.OPEN) {
            console.log(`[WS] T+${t()}ms: WebSocket closed, stopping stream`);
            break;
          }

          // Transform SDK messages to match HTTP stream format
          if (msg.type === 'stream_event') {
            // Update actual session_id if present
            if (msg.session_id) {
              actualSessionId = msg.session_id;
            }
            ws.send(JSON.stringify({ ...msg, type: 'stream' }) + '\n');
          } else if (msg.type === 'assistant') {
            // Extract text and tool_use blocks
            for (const block of msg.message.content) {
              if (block.type === 'text') {
                ws.send(JSON.stringify({ type: 'content', text: block.text }) + '\n');
              } else if (block.type === 'tool_use') {
                ws.send(JSON.stringify({
                  type: 'tool_use',
                  id: block.id,
                  name: block.name,
                  input: block.input,
                }) + '\n');
              }
            }
          } else if (msg.type === 'result') {
            // Send done with usage info
            ws.send(JSON.stringify({
              type: 'done',
              sessionId: msg.session_id,
              usage: {
                inputTokens: msg.usage.input_tokens,
                outputTokens: msg.usage.output_tokens,
              },
            }) + '\n');
          }
        }

        console.log(`[WS] T+${t()}ms: Chat stream completed`);

        // Close connection after completion
        if (ws.readyState === WebSocket.OPEN) {
          ws.close(1000, 'Complete');
        }
      } catch (error) {
        console.error(`[WS] T+${t()}ms: Error:`, error);

        if (ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: 'error',
              error: (error as Error).message,
            }) + '\n'
          );
          ws.close(1011, 'Error');
        }
      }
    },

    close(ws, code, reason) {
      activeConnections.delete(ws);
      console.log(`[WS] Connection closed (code: ${code}, reason: ${reason}, remaining: ${activeConnections.size})`);
    },
  },
});

console.log(`Maven Agent listening on http://${hostname}:${port} (Bun runtime)`);
console.log(`WebSocket endpoint: ws://${hostname}:${port}/ws/chat`);

// Graceful shutdown handler
const shutdown = async (signal: string) => {
  console.log(`[Agent] ${signal} received, closing ${activeConnections.size} connections`);

  for (const ws of activeConnections) {
    try {
      ws.close(1012, 'Server restarting');
    } catch {
      // Already closed
    }
  }

  // Flush any remaining logs before exit
  await shutdownLogger();

  // Brief drain period
  await new Promise(r => setTimeout(r, 500));
  process.exit(0);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
