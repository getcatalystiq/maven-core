/**
 * OAuth authorization initiation with automatic discovery
 * Uses RFC 8414 OAuth 2.0 Authorization Server Metadata
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import {
  getConnectorById,
  setOAuthState,
  discoverOAuthEndpoints,
  getMcpServerUrl,
} from '../../services/connectors';
import type { Env, Variables } from '../../index';

/**
 * Validate that a redirect URI is allowed
 * Only allows callbacks to our own domain
 */
function validateRedirectUri(requestUrl: string, redirectUri: string): boolean {
  try {
    const requestOrigin = new URL(requestUrl).origin;
    const redirectUrl = new URL(redirectUri);

    // Only allow redirects to the same origin as the request
    // This prevents open redirect attacks
    return redirectUrl.origin === requestOrigin;
  } catch {
    return false;
  }
}

/**
 * Generate a cryptographically secure code verifier for PKCE
 * RFC 7636: 43-128 characters from unreserved characters
 */
function generateCodeVerifier(): string {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return base64UrlEncode(array);
}

/**
 * Generate code challenge from verifier using S256 method
 */
async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return base64UrlEncode(new Uint8Array(digest));
}

/**
 * Base64 URL encoding (RFC 4648)
 */
function base64UrlEncode(buffer: Uint8Array): string {
  let binary = '';
  for (let i = 0; i < buffer.length; i++) {
    binary += String.fromCharCode(buffer[i]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

const app = new Hono<{ Bindings: Env; Variables: Variables }>();

app.get('/:connectorId', async (c) => {
  const connectorId = c.req.param('connectorId');
  const tenantId = c.get('tenantId');
  const userId = c.get('userId');

  // Build default redirect URI using our own domain
  const defaultRedirectUri = `${new URL(c.req.url).origin}/oauth/${connectorId}/callback`;

  // Get redirect URI from query param or use default
  const redirectUri = c.req.query('redirect_uri') || defaultRedirectUri;

  // Validate redirect URI to prevent open redirect attacks
  if (!validateRedirectUri(c.req.url, redirectUri)) {
    throw new HTTPException(400, {
      message: 'Invalid redirect_uri: must be on the same domain',
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
      message: 'Connector does not have an MCP server URL (requires http or sse type)',
    });
  }

  // Discover OAuth endpoints from MCP server
  const oauthMetadata = await discoverOAuthEndpoints(mcpServerUrl);
  if (!oauthMetadata) {
    throw new HTTPException(400, {
      message: `MCP server does not support OAuth discovery at ${mcpServerUrl}/.well-known/oauth-authorization-server`,
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
