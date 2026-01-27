/**
 * Sessions management routes
 */

import { Hono } from 'hono';

const app = new Hono();

// Note: Session management is primarily handled by the Claude Agent SDK
// These endpoints provide basic session listing and cleanup functionality

// List sessions
app.get('/', async (c) => {
  // Sessions are managed by the SDK, so we don't have direct access here
  // In a full implementation, you would track sessions in a database
  return c.json({
    sessions: [],
    message: 'Session listing not implemented - sessions are managed by the SDK',
  });
});

// Get session details
app.get('/:id', async (c) => {
  const sessionId = c.req.param('id');

  // Session details would be stored in a database in a full implementation
  return c.json({
    id: sessionId,
    message: 'Session details not implemented - use sessionId in chat requests to resume',
  });
});

// Delete session
app.delete('/:id', async (c) => {
  const sessionId = c.req.param('id');

  // Session deletion would clear stored state in a full implementation
  return c.json({
    message: `Session ${sessionId} marked for deletion`,
  });
});

export { app as sessionsRoute };
