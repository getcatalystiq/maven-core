/**
 * Streaming chat route handler
 * Uses Streamable HTTP (NDJSON) per MCP 2025 spec
 *
 * Leverages streaming input mode to keep SDK processes alive between messages,
 * reducing response time from ~10s to ~2s for subsequent messages.
 */

import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { chatRequestSchema } from '@maven/shared';
import { getOrCreateSession, sendMessage, getSessionStats } from '../session-manager';

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
 * Session stats endpoint with version info
 */
app.get('/stats', (c) => {
  return c.json({
    version: 'v1.3.3-streaming-input',
    ...getSessionStats(),
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
          // Get or create session (streaming input mode keeps process alive)
          console.log(`[STREAM] T+${t()}ms: Getting session...`);
          const session = await getOrCreateSession(
            sessionId,
            tenantId,
            userId,
            userRoles
          );

          const sessionWarmup = t();
          console.log(`[STREAM] T+${sessionWarmup}ms: Session ready (${session.messageCount > 0 ? 'WARM' : 'COLD'})`);

          // Emit session info
          controller.enqueue(
            encoder.encode(ndjsonLine({
              type: 'session_info',
              sessionId: session.id,
              isWarm: session.messageCount > 0,
              messageCount: session.messageCount,
              warmupMs: sessionWarmup,
            }))
          );

          // Send message and stream responses
          console.log(`[STREAM] T+${t()}ms: Sending message...`);

          for await (const msg of sendMessage(session, message)) {
            if (!firstMsgTime) {
              firstMsgTime = t();
              console.log(`[STREAM] T+${firstMsgTime}ms: First message from SDK (type: ${msg.type})`);
            }

            if (msg.type === 'stream_event') {
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
                    sessionId: msg.session_id || session.id,
                    usage: {
                      inputTokens: msg.usage.input_tokens,
                      outputTokens: msg.usage.output_tokens,
                    },
                    timing: {
                      totalMs: t(),
                      firstMsgMs: firstMsgTime,
                      isWarm: session.messageCount > 1,
                    },
                  })
                )
              );
            }
          }

          console.log(`[STREAM] T+${t()}ms: Message completed`);
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
