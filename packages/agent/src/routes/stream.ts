/**
 * Streaming chat route handler
 * Uses Streamable HTTP (NDJSON) per MCP 2025 spec
 *
 * Uses the same chat() generator as the main agent for reliable streaming.
 */

import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { chatRequestSchema } from '@maven/shared';
import { chat, type TimingEvent } from '../agent';

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
 * Stats endpoint
 */
app.get('/stats', (c) => {
  return c.json({
    version: 'v1.3.4-fixed-streaming',
  });
});

app.post(
  '/',
  zValidator('json', chatRequestSchema),
  async (c) => {
    const t0 = Date.now();
    const t = () => Date.now() - t0;

    console.log(`[STREAM] T+${t()}ms: Request received`);

    const { message, sessionId: requestedSessionId, skills } = c.req.valid('json');

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

        // Emit start event immediately to reduce TTFB
        controller.enqueue(
          encoder.encode(ndjsonLine({ type: 'start', sessionId }))
        );
        console.log(`[STREAM] T+${t()}ms: Emitted start event`);

        try {
          console.log(`[STREAM] T+${t()}ms: Calling chat() function`);

          // Use the working chat() generator from agent.ts
          for await (const msg of chat(message, {
            sessionId,
            tenantId,
            userId,
            userRoles,
            skills,
          })) {
            if (!firstMsgTime) {
              firstMsgTime = t();
              console.log(`[STREAM] T+${firstMsgTime}ms: First message from Claude SDK (type: ${msg.type})`);
            }

            // Handle timing events (custom type from chat())
            if (msg.type === 'timing') {
              const timing = msg as TimingEvent;
              controller.enqueue(
                encoder.encode(ndjsonLine({
                  type: 'timing',
                  phase: timing.phase,
                  ms: timing.ms,
                  details: timing.details,
                }))
              );
            } else if (msg.type === 'stream_event') {
              controller.enqueue(
                encoder.encode(ndjsonLine({ ...msg, type: 'stream' }))
              );
            } else if (msg.type === 'assistant') {
              // Extract text for immediate display
              for (const block of msg.message.content) {
                if (block.type === 'text') {
                  controller.enqueue(
                    encoder.encode(ndjsonLine({ type: 'content', text: block.text }))
                  );
                } else if (block.type === 'tool_use') {
                  controller.enqueue(
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
              controller.enqueue(
                encoder.encode(
                  ndjsonLine({
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
                  })
                )
              );
            }
          }

          console.log(`[STREAM] T+${t()}ms: Chat loop completed`);
        } catch (error) {
          const errorMessage = (error as Error).message;
          // Ignore "exit code 1" errors if we already received a result
          if (receivedResult && errorMessage.includes('exited with code 1')) {
            console.log('Ignoring exit code 1 after successful result');
          } else {
            console.error(`[STREAM] T+${t()}ms: Error:`, error);
            controller.enqueue(
              encoder.encode(ndjsonLine({ type: 'error', message: errorMessage }))
            );
          }
        } finally {
          console.log(`[STREAM] T+${t()}ms: Closing controller`);
          controller.close();
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
