/**
 * Connector management admin routes
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import { createConnectorSchema, updateConnectorSchema, paginationSchema } from '@maven/shared';
import {
  createConnector,
  getConnectorById,
  getConnectorByName,
  listConnectors,
  updateConnector,
  deleteConnector,
  setConnectorSecret,
  deleteConnectorSecret,
  deleteAllConnectorTokens,
} from '../../services/connectors';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// List connectors
app.get('/', zValidator('query', paginationSchema), async (c) => {
  const tenantId = c.get('tenantId');
  const { offset, limit } = c.req.valid('query');

  const result = await listConnectors(c.env.DB, tenantId, offset, limit);

  // Remove sensitive info from response
  const connectors = result.connectors.map((conn) => ({
    ...conn,
    oauthClientSecret: undefined,
  }));

  return c.json({
    connectors,
    total: result.total,
    offset,
    limit,
  });
});

// Get single connector
app.get('/:id', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const connector = await getConnectorById(c.env.DB, id);
  if (!connector || connector.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Connector not found' });
  }

  return c.json(connector);
});

// Create connector
app.post('/', zValidator('json', createConnectorSchema), async (c) => {
  const tenantId = c.get('tenantId');
  const { name, type, config, oauthClientId, oauthClientSecret, oauthScopes } = c.req.valid('json');

  // Check for duplicate name
  const existing = await getConnectorByName(c.env.DB, tenantId, name);
  if (existing) {
    throw new HTTPException(409, { message: 'Connector with this name already exists' });
  }

  const connectorId = crypto.randomUUID();

  const connector = await createConnector(c.env.DB, {
    id: connectorId,
    tenantId,
    name,
    type,
    config,
    oauthClientId,
    oauthScopes,
    enabled: true,
  });

  // Store client secret in KV if provided
  if (oauthClientSecret) {
    await setConnectorSecret(c.env.KV, connectorId, oauthClientSecret);
  }

  return c.json(connector, 201);
});

// Update connector
app.patch('/:id', zValidator('json', updateConnectorSchema), async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');
  const updates = c.req.valid('json');

  const connector = await getConnectorById(c.env.DB, id);
  if (!connector || connector.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Connector not found' });
  }

  // Check for duplicate name if changing
  if (updates.name && updates.name !== connector.name) {
    const existing = await getConnectorByName(c.env.DB, tenantId, updates.name);
    if (existing) {
      throw new HTTPException(409, { message: 'Connector with this name already exists' });
    }
  }

  await updateConnector(c.env.DB, id, updates);

  const updatedConnector = await getConnectorById(c.env.DB, id);
  return c.json(updatedConnector);
});

// Enable/disable connector
app.post('/:id/enable', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const connector = await getConnectorById(c.env.DB, id);
  if (!connector || connector.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Connector not found' });
  }

  await updateConnector(c.env.DB, id, { enabled: true });
  return c.json({ message: 'Connector enabled' });
});

app.post('/:id/disable', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const connector = await getConnectorById(c.env.DB, id);
  if (!connector || connector.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Connector not found' });
  }

  await updateConnector(c.env.DB, id, { enabled: false });
  return c.json({ message: 'Connector disabled' });
});

// Delete connector
app.delete('/:id', async (c) => {
  const id = c.req.param('id');
  const tenantId = c.get('tenantId');

  const connector = await getConnectorById(c.env.DB, id);
  if (!connector || connector.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Connector not found' });
  }

  // Clean up KV entries: secret and all user tokens
  await Promise.all([
    deleteConnector(c.env.DB, id),
    deleteConnectorSecret(c.env.KV, id),
    deleteAllConnectorTokens(c.env.KV, tenantId, id),
  ]);

  return c.json({ message: 'Connector deleted' });
});

export { app as connectorsRoute };
