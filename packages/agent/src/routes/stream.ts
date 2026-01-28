/**
 * Streaming chat route handler - V2 Session Manager
 *
 * Uses the V2 Session API for warm starts (~2-3s) after the first cold start (~10s).
 * Sessions are kept alive and reused for subsequent messages.
 */

import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { chatRequestSchema } from '@maven/shared';
import {
  getOrCreateSession,
  sendMessage,
  getSessionStats,
} from '../session-manager';

const app = new Hono();

/**
 * Safely parse roles from header
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

/**
 * Write NDJSON line to stream
 */
function ndjsonLine(data: unknown): string {
  return JSON.stringify(data) + '\n';
}

/**
 * Stats endpoint - shows session manager statistics
 */
app.get('/stats', (c) => {
  const stats = getSessionStats();
  return c.json({
    version: 'v2.0.0-session-manager',
    ...stats,
  });
});

app.post(
  '/',
  zValidator('json', chatRequestSchema),
  async (c) => {
    const t0 = Date.now();
    const t = () => Date.now() - t0;

    console.log(`[STREAM] T+${t()}ms: Request received`);

    const { message, sessionId: requestedSessionId } = c.req.valid('json');

    // Get context from headers (tenant required)
    const tenantId = c.req.header('X-Tenant-Id');
    if (!tenantId) {
      return c.json({ error: 'X-Tenant-Id header is required' }, 400);
    }
    const userId = c.req.header('X-User-Id') || 'anonymous';
    const userRoles = safeParseRoles(c.req.header('X-User-Roles'));

    // Generate session ID if not provided
    const sessionId = requestedSessionId || crypto.randomUUID();

    console.log(`[STREAM] T+${t()}ms: Parsed request, session=${sessionId}`);

    const encoder = new TextEncoder();

    const stream = new ReadableStream({
      async start(controller) {
        console.log(`[STREAM] T+${t()}ms: ReadableStream.start() called`);

        let receivedResult = false;
        let firstMsgTime: number | null = null;
        let controllerClosed = false;

        // Safe enqueue that checks if controller is still open
        const safeEnqueue = (data: Uint8Array) => {
          if (!controllerClosed) {
            try {
              controller.enqueue(data);
            } catch (e) {
              console.log(`[STREAM] T+${t()}ms: Enqueue failed (controller closed)`);
              controllerClosed = true;
            }
          }
        };

        // Safe close that only closes once
        const safeClose = () => {
          if (!controllerClosed) {
            controllerClosed = true;
            try {
              controller.close();
            } catch (e) {
              console.log(`[STREAM] T+${t()}ms: Close failed (already closed)`);
            }
          }
        };

        try {
          // Get or create session (warm path is instant, cold path creates SDK session)
          console.log(`[STREAM] T+${t()}ms: Getting/creating session...`);
          const session = await getOrCreateSession(
            sessionId,
            tenantId,
            userId,
            userRoles
          );

          const isWarm = session.messageCount > 0;
          const sessionInfoTime = t();
          console.log(`[STREAM] T+${sessionInfoTime}ms: Session ready (warm=${isWarm}, msgCount=${session.messageCount})`);

          // Emit session info event - includes warm status for client telemetry
          safeEnqueue(
            encoder.encode(ndjsonLine({
              type: 'session_info',
              sessionId: session.id,
              isWarm,
              messageCount: session.messageCount,
              timing: {
                sessionReadyMs: sessionInfoTime,
              },
            }))
          );

          // Emit start event
          safeEnqueue(
            encoder.encode(ndjsonLine({ type: 'start', sessionId }))
          );
          console.log(`[STREAM] T+${t()}ms: Emitted start event`);

          // Send message and stream responses
          console.log(`[STREAM] T+${t()}ms: Sending message to session...`);

          for await (const msg of sendMessage(session, message)) {
            if (!firstMsgTime) {
              firstMsgTime = t();
              console.log(`[STREAM] T+${firstMsgTime}ms: First message from SDK (type: ${msg.type})`);
            }

            // Handle different message types
            if (msg.type === 'system') {
              // System init message - emit for debugging
              safeEnqueue(
                encoder.encode(ndjsonLine({
                  type: 'system',
                  subtype: 'subtype' in msg ? msg.subtype : 'unknown',
                }))
              );
            } else if (msg.type === 'stream_event') {
              safeEnqueue(
                encoder.encode(ndjsonLine({ ...msg, type: 'stream' }))
              );
            } else if (msg.type === 'assistant') {
              // Extract text and emit in format widget expects
              // Widget expects: {"type":"stream","event":{"type":"content_block_delta","delta":{"text":"..."}}}
              for (const block of msg.message.content) {
                if (block.type === 'text') {
                  // Emit as stream event for widget compatibility
                  safeEnqueue(
                    encoder.encode(ndjsonLine({
                      type: 'stream',
                      event: {
                        type: 'content_block_delta',
                        delta: { text: block.text },
                      },
                    }))
                  );
                } else if (block.type === 'tool_use') {
                  safeEnqueue(
                    encoder.encode(
                      ndjsonLine({
                        type: 'tool_use',
                        id: block.id,
                        name: block.name,
                        input: block.input,
                      })
                    )
                  );
                }
              }
            } else if (msg.type === 'result') {
              receivedResult = true;
              safeEnqueue(
                encoder.encode(
                  ndjsonLine({
                    type: 'done',
                    sessionId: msg.session_id || sessionId,
                    isWarm,
                    usage: {
                      inputTokens: msg.usage.input_tokens,
                      outputTokens: msg.usage.output_tokens,
                    },
                    timing: {
                      totalMs: t(),
                      firstMsgMs: firstMsgTime,
                    },
                  })
                )
              );
            }
          }

          console.log(`[STREAM] T+${t()}ms: Message loop completed`);
        } catch (error) {
          const errorMessage = (error as Error).message;
          // Ignore "exit code 1" errors if we already received a result
          if (receivedResult && errorMessage.includes('exited with code 1')) {
            console.log('Ignoring exit code 1 after successful result');
          } else {
            console.error(`[STREAM] T+${t()}ms: Error:`, error);
            safeEnqueue(
              encoder.encode(ndjsonLine({ type: 'error', message: errorMessage }))
            );
          }
        } finally {
          console.log(`[STREAM] T+${t()}ms: Closing controller`);
          safeClose();
        }
      },
    });

    console.log(`[STREAM] T+${t()}ms: Returning Response with stream`);
    return new Response(stream, {
      headers: {
        'Content-Type': 'application/x-ndjson',
        'Cache-Control': 'no-cache',
        'Transfer-Encoding': 'chunked',
      },
    });
  }
);

export { app as streamRoute };
