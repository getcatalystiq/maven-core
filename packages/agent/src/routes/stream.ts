/**
 * Streaming chat route handler - V1 Query API
 *
 * Uses the V1 query() API with includePartialMessages: true for real-time streaming.
 * Each request spawns a new query - no session reuse.
 */

import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { chatRequestSchema } from '@maven/shared';
import { chat } from '../agent';

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
 * Stats endpoint - V1 has no session stats
 */
app.get('/stats', (c) => {
  return c.json({
    version: 'v1.0.0-query-api',
    note: 'V1 query API - no session persistence',
  });
});

app.post(
  '/',
  zValidator('json', chatRequestSchema),
  async (c) => {
    const t0 = Date.now();
    const t = () => Date.now() - t0;

    console.log(`[STREAM] T+${t()}ms: Request received`);

    const { message, sessionId: requestedSessionId, sessionPath } = c.req.valid('json');

    // Get context from headers (tenant required)
    const tenantId = c.req.header('X-Tenant-Id');
    if (!tenantId) {
      return c.json({ error: 'X-Tenant-Id header is required' }, 400);
    }
    const userId = c.req.header('X-User-Id') || 'anonymous';
    const userRoles = safeParseRoles(c.req.header('X-User-Roles'));

    // Generate session ID if not provided
    const sessionId = requestedSessionId || crypto.randomUUID();

    console.log(`[STREAM] T+${t()}ms: Parsed request, session=${sessionId}, sessionPath=${sessionPath || 'none'}`);

    const encoder = new TextEncoder();

    // AbortController for cancellation propagation
    const abortController = new AbortController();

    const stream = new ReadableStream({
      async start(controller) {
        console.log(`[STREAM] T+${t()}ms: ReadableStream.start() called`);

        let receivedResult = false;
        let receivedStreamEvents = false;  // Track if we got incremental stream events
        let firstMsgTime: number | null = null;
        let controllerClosed = false;
        let sdkSessionId: string | undefined;

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
          // Emit start event
          safeEnqueue(
            encoder.encode(ndjsonLine({ type: 'start', sessionId }))
          );
          console.log(`[STREAM] T+${t()}ms: Emitted start event`);

          // Use V1 chat() which has includePartialMessages: true for streaming
          console.log(`[STREAM] T+${t()}ms: Starting V1 chat() with sessionPath=${sessionPath || 'none'}...`);

          for await (const msg of chat(message, {
            sessionId,
            sessionPath, // Session workspace path for native skill loading
            tenantId,
            userId,
            userRoles,
          })) {
            // Check if client disconnected
            if (abortController.signal.aborted) {
              console.log(`[STREAM] T+${t()}ms: Client disconnected, stopping`);
              break;
            }

            if (!firstMsgTime && msg.type !== 'timing') {
              firstMsgTime = t();
              console.log(`[STREAM] T+${firstMsgTime}ms: First SDK message (type: ${msg.type})`);
            }

            // Handle different message types
            if (msg.type === 'timing') {
              // Internal timing event - emit for telemetry
              safeEnqueue(
                encoder.encode(ndjsonLine({
                  type: 'timing',
                  phase: msg.phase,
                  ms: msg.ms,
                  details: msg.details,
                }))
              );
            } else if (msg.type === 'system') {
              // System init message
              safeEnqueue(
                encoder.encode(ndjsonLine({
                  type: 'system',
                  subtype: 'subtype' in msg ? msg.subtype : 'unknown',
                }))
              );
            } else if (msg.type === 'stream_event') {
              // Incremental streaming event - this is the key for real-time streaming!
              receivedStreamEvents = true;

              // Filter out "summary" content_block_delta events (no index = final summary, skip it)
              // SDK sends both incremental deltas (with index) and a final complete delta (without index)
              const event = msg.event as { type?: string; index?: number };
              if (event.type === 'content_block_delta' && event.index === undefined) {
                console.log(`[STREAM] T+${t()}ms: Skipping summary delta (no index)`);
                continue;
              }

              // Pass through incremental events for widget to consume
              safeEnqueue(
                encoder.encode(ndjsonLine({
                  type: 'stream',
                  event: msg.event,
                }))
              );
            } else if (msg.type === 'assistant') {
              // Complete assistant message - SKIP if we already got stream events (avoid duplicates)
              if (receivedStreamEvents) {
                console.log(`[STREAM] T+${t()}ms: Skipping assistant message (already streamed)`);
                continue;
              }
              // Fallback: emit as stream if no stream_event was received
              for (const block of msg.message.content) {
                if (block.type === 'text') {
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
                    encoder.encode(ndjsonLine({
                      type: 'tool_use',
                      id: block.id,
                      name: block.name,
                      input: block.input,
                    }))
                  );
                }
              }
            } else if (msg.type === 'result') {
              receivedResult = true;
              sdkSessionId = msg.session_id;
              safeEnqueue(
                encoder.encode(ndjsonLine({
                  type: 'done',
                  sessionId: msg.session_id || sessionId,
                  usage: {
                    inputTokens: msg.usage.input_tokens,
                    outputTokens: msg.usage.output_tokens,
                  },
                  timing: {
                    totalMs: t(),
                    firstMsgMs: firstMsgTime,
                  },
                }))
              );
            }
          }

          console.log(`[STREAM] T+${t()}ms: Chat completed, SDK session: ${sdkSessionId}`);
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

      cancel(reason) {
        console.log(`[STREAM] Client disconnected:`, reason);
        abortController.abort();
      },
    });

    console.log(`[STREAM] T+${t()}ms: Returning Response with stream`);
    return new Response(stream, {
      headers: {
        'Content-Type': 'application/x-ndjson',
        'Cache-Control': 'no-cache',
        'Transfer-Encoding': 'chunked',
        'Content-Encoding': 'identity',
      },
    });
  }
);

export { app as streamRoute };
