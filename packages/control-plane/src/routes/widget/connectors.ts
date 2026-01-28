/**
 * Widget-specific connector routes
 *
 * These endpoints are designed for the maven-widget frontend and include
 * user-specific connection status. Authentication uses JWT only (no admin role required).
 *
 * SECURITY: userId comes from JWT sub claim, NOT from query parameters.
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import { generateCodeVerifier, generateCodeChallenge, oauthInitiateSchema } from '@maven/shared';
import type {
  WidgetConnector,
  WidgetConnectorListResponse,
  OAuthInitiateResponse,
  DisconnectResponse,
} from '@maven/shared';
import {
  listEnabledConnectors,
  getConnectorById,
  getConnectorToken,
  deleteConnectorToken,
  setOAuthState,
  discoverOAuthEndpointsCached,
  getMcpServerUrl,
  validateRedirectUri,
} from '../../services/connectors';
import type { Env, Variables } from '../../index';

// UUID validation regex
const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

/**
 * Middleware to validate tenantId is present
 * Super-admins without tenant context cannot use widget endpoints
 */
app.use('*', async (c, next) => {
  const tenantId = c.get('tenantId');
  if (!tenantId) {
    throw new HTTPException(400, {
      message: 'Tenant context required. Super-admins must specify X-Tenant-Id header.',
    });
  }
  await next();
});

/**
 * GET /widget/connectors
 *
 * List all enabled connectors with user-specific connection status.
 * User ID is derived from JWT, not query parameters.
 */
app.get('/', async (c) => {
  const tenantId = c.get('tenantId');
  const userId = c.get('userId');

  // Get enabled connectors
  const connectors = await listEnabledConnectors(c.env.DB, tenantId);

  if (connectors.length === 0) {
    const response: WidgetConnectorListResponse = { connectors: [] };
    return c.json(response);
  }

  // Parallel KV lookups for token status
  const tokenChecks = await Promise.all(
    connectors.map(async (connector) => {
      const token = await getConnectorToken(c.env.KV, tenantId, userId, connector.id);
      return {
        id: connector.id,
        connected: !!token,
        expiresAt: token?.expiresAt || null,
      };
    })
  );

  // Build lookup map
  const tokenMap = new Map(tokenChecks.map((t) => [t.id, t]));

  // Transform to widget response format
  const widgetConnectors: WidgetConnector[] = connectors.map((connector) => ({
    id: connector.id,
    name: connector.name,
    description: connector.description || null,
    mcpServerUrl: getMcpServerUrl(connector),
    requiresOauth: !!connector.oauthClientId,
    connected: tokenMap.get(connector.id)?.connected ?? false,
    expiresAt: tokenMap.get(connector.id)?.expiresAt ?? null,
  }));

  const response: WidgetConnectorListResponse = { connectors: widgetConnectors };

  // Cache for 30 seconds (private since it contains user-specific data)
  c.header('Cache-Control', 'private, max-age=30');

  return c.json(response);
});

/**
 * POST /widget/connectors/:connectorId/oauth/initiate
 *
 * Initiate OAuth flow for a connector. Returns an authorization URL
 * that the widget can open in a popup.
 *
 * SECURITY: userId comes from JWT, not request body.
 */
app.post(
  '/:connectorId/oauth/initiate',
  zValidator('json', oauthInitiateSchema),
  async (c) => {
    const connectorId = c.req.param('connectorId');
    const tenantId = c.get('tenantId');
    const userId = c.get('userId');
    const { redirectUri } = c.req.valid('json');

    // Validate connectorId is a valid UUID
    if (!UUID_REGEX.test(connectorId)) {
      throw new HTTPException(400, { message: 'Invalid connector ID format' });
    }

    // Validate redirect URI against allowed origins
    if (!validateRedirectUri(c.env, redirectUri)) {
      throw new HTTPException(400, {
        message: 'Invalid redirect_uri: not in allowed origins',
      });
    }

    // Get connector with tenant isolation check
    const connector = await getConnectorById(c.env.DB, connectorId);
    if (!connector || connector.tenantId !== tenantId) {
      throw new HTTPException(404, { message: 'Connector not found' });
    }

    // Get MCP server URL
    const mcpServerUrl = getMcpServerUrl(connector);
    if (!mcpServerUrl) {
      throw new HTTPException(400, {
        message: 'Connector does not support OAuth (requires http or sse type)',
      });
    }

    // Discover OAuth endpoints (cached)
    const oauthMetadata = await discoverOAuthEndpointsCached(c.env.KV, mcpServerUrl);
    if (!oauthMetadata) {
      console.error(`OAuth discovery failed for connector ${connectorId}`);
      throw new HTTPException(400, {
        message: 'Connector MCP server does not support OAuth discovery',
      });
    }

    // Generate state and nonce
    const state = crypto.randomUUID();
    const nonce = crypto.randomUUID();

    // Build authorization URL
    const scopes = connector.oauthScopes || oauthMetadata.scopes_supported || [];
    const authParams = new URLSearchParams({
      redirect_uri: redirectUri,
      response_type: 'code',
      scope: scopes.join(' '),
      state,
      nonce,
    });

    // Use connector's client ID if configured, otherwise use redirect URI
    if (connector.oauthClientId) {
      authParams.set('client_id', connector.oauthClientId);
    } else {
      authParams.set('client_id', redirectUri);
    }

    // Add PKCE if supported by the authorization server (consistent with oauth/authorize.ts)
    let codeVerifier: string | undefined;
    if (oauthMetadata.code_challenge_methods_supported?.includes('S256')) {
      codeVerifier = generateCodeVerifier();
      const codeChallenge = await generateCodeChallenge(codeVerifier);
      authParams.set('code_challenge', codeChallenge);
      authParams.set('code_challenge_method', 'S256');
    }

    // Store state in KV (10 min TTL, single-use)
    await setOAuthState(c.env.KV, state, {
      connectorId,
      tenantId,
      userId,
      redirectUri,
      nonce,
      codeVerifier,
      tokenEndpoint: oauthMetadata.token_endpoint,
    });

    const authorizationUrl = `${oauthMetadata.authorization_endpoint}?${authParams.toString()}`;

    const response: OAuthInitiateResponse = { authorizationUrl };
    return c.json(response);
  }
);

/**
 * POST /widget/connectors/:connectorId/disconnect
 *
 * Disconnect a user from a connector by deleting their OAuth token.
 *
 * SECURITY: userId comes from JWT, not request body.
 */
app.post('/:connectorId/disconnect', async (c) => {
  const connectorId = c.req.param('connectorId');
  const tenantId = c.get('tenantId');
  const userId = c.get('userId');

  // Validate connectorId is a valid UUID
  if (!UUID_REGEX.test(connectorId)) {
    throw new HTTPException(400, { message: 'Invalid connector ID format' });
  }

  // Verify connector exists and belongs to tenant
  const connector = await getConnectorById(c.env.DB, connectorId);
  if (!connector || connector.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Connector not found' });
  }

  // Check if token exists (prevent enumeration by returning same error)
  const existingToken = await getConnectorToken(c.env.KV, tenantId, userId, connectorId);
  if (!existingToken) {
    throw new HTTPException(404, { message: 'Connection not found' });
  }

  // Delete token
  await deleteConnectorToken(c.env.KV, tenantId, userId, connectorId);

  const response: DisconnectResponse = { disconnected: true };
  return c.json(response);
});

export { app as widgetConnectorsRoute };
