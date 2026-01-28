/**
 * OAuth authorization initiation with automatic discovery
 * Uses RFC 8414 OAuth 2.0 Authorization Server Metadata
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import { generateCodeVerifier, generateCodeChallenge } from '@maven/shared';
import {
  getConnectorById,
  setOAuthState,
  discoverOAuthEndpointsCached,
  getMcpServerUrl,
  validateRedirectUri,
} from '../../services/connectors';
import type { Env, Variables } from '../../index';

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

app.get('/:connectorId', async (c) => {
  const connectorId = c.req.param('connectorId');
  const tenantId = c.get('tenantId');
  const userId = c.get('userId');

  // Validate connectorId is a valid UUID
  const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!uuidRegex.test(connectorId)) {
    throw new HTTPException(400, { message: 'Invalid connector ID format' });
  }

  // Build default redirect URI using our own domain
  const defaultRedirectUri = `${new URL(c.req.url).origin}/oauth/${connectorId}/callback`;

  // Get redirect URI from query param or use default
  const redirectUri = c.req.query('redirect_uri') || defaultRedirectUri;

  // Validate redirect URI to prevent open redirect attacks
  if (!validateRedirectUri(c.env, redirectUri)) {
    throw new HTTPException(400, {
      message: 'Invalid redirect_uri: not in allowed origins',
    });
  }

  // Get connector
  const connector = await getConnectorById(c.env.DB, connectorId);
  if (!connector || connector.tenantId !== tenantId) {
    throw new HTTPException(404, { message: 'Connector not found' });
  }

  // Get MCP server URL from connector config
  const mcpServerUrl = getMcpServerUrl(connector);
  if (!mcpServerUrl) {
    throw new HTTPException(400, {
      message: 'Connector does not support OAuth (requires http or sse type)',
    });
  }

  // Discover OAuth endpoints from MCP server (cached)
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

  // Use connector's client ID if configured, otherwise use redirect URI as client ID
  // (some MCP servers use the callback URL as the client identifier)
  if (connector.oauthClientId) {
    authParams.set('client_id', connector.oauthClientId);
  } else {
    authParams.set('client_id', redirectUri);
  }

  // Add PKCE if supported by the authorization server
  let codeVerifier: string | undefined;
  if (oauthMetadata.code_challenge_methods_supported?.includes('S256')) {
    codeVerifier = generateCodeVerifier();
    const codeChallenge = await generateCodeChallenge(codeVerifier);
    authParams.set('code_challenge', codeChallenge);
    authParams.set('code_challenge_method', 'S256');
  }

  // Store state in KV with discovered token endpoint
  await setOAuthState(c.env.KV, state, {
    connectorId,
    tenantId,
    userId,
    redirectUri,
    nonce,
    codeVerifier,
    tokenEndpoint: oauthMetadata.token_endpoint,
  });

  const authUrl = `${oauthMetadata.authorization_endpoint}?${authParams.toString()}`;

  return c.redirect(authUrl);
});

export { app as authorizeRoute };
