/**
 * OAuth callback handler
 * Exchanges authorization code for tokens using discovered endpoint
 */

import { Hono } from 'hono';
import { HTTPException } from 'hono/http-exception';
import {
  getConnectorById,
  getOAuthState,
  deleteOAuthState,
  setConnectorToken,
  getConnectorSecret,
} from '../../services/connectors';
import type { Env } from '../../index';

/**
 * Escape HTML special characters to prevent XSS
 */
function escapeHtml(str: string): string {
  const htmlEscapes: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  };
  return str.replace(/[&<>"']/g, (char) => htmlEscapes[char]);
}

const app = new Hono<{ Bindings: Env }>();

app.get('/:connectorId', async (c) => {
  const connectorId = c.req.param('connectorId');
  const code = c.req.query('code');
  const state = c.req.query('state');
  const error = c.req.query('error');
  const errorDescription = c.req.query('error_description');

  // Handle OAuth errors
  if (error) {
    const safeError = escapeHtml(error);
    const safeDescription = escapeHtml(errorDescription || 'Unknown error');
    return c.html(
      `<html><body><h1>OAuth Error</h1><p>${safeError}: ${safeDescription}</p></body></html>`,
      400
    );
  }

  if (!code || !state) {
    throw new HTTPException(400, { message: 'Missing code or state parameter' });
  }

  // Get and validate state
  const stateData = await getOAuthState(c.env.KV, state);
  if (!stateData) {
    throw new HTTPException(400, { message: 'Invalid or expired state' });
  }

  if (stateData.connectorId !== connectorId) {
    throw new HTTPException(400, { message: 'Connector ID mismatch' });
  }

  // Clean up state
  await deleteOAuthState(c.env.KV, state);

  // Get connector
  const connector = await getConnectorById(c.env.DB, connectorId);
  if (!connector) {
    throw new HTTPException(404, { message: 'Connector not found' });
  }

  // Build token request using discovered endpoint from state
  const tokenParams = new URLSearchParams({
    code,
    grant_type: 'authorization_code',
    redirect_uri: stateData.redirectUri,
  });

  // Use connector's client ID if configured, otherwise use redirect URI as client ID
  if (connector.oauthClientId) {
    tokenParams.set('client_id', connector.oauthClientId);
  } else {
    tokenParams.set('client_id', stateData.redirectUri);
  }

  // Add client secret if configured
  const clientSecret = await getConnectorSecret(c.env.KV, connectorId);
  if (clientSecret) {
    tokenParams.set('client_secret', clientSecret);
  }

  // Add PKCE verifier if used during authorization
  if (stateData.codeVerifier) {
    tokenParams.set('code_verifier', stateData.codeVerifier);
  }

  // Exchange code for token using discovered token endpoint
  const tokenResponse = await fetch(stateData.tokenEndpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
    },
    body: tokenParams.toString(),
  });

  if (!tokenResponse.ok) {
    const errorText = await tokenResponse.text();
    console.error('Token exchange failed:', errorText);
    throw new HTTPException(500, { message: 'Failed to exchange authorization code' });
  }

  const tokenData = (await tokenResponse.json()) as {
    access_token: string;
    refresh_token?: string;
    expires_in?: number;
    token_type?: string;
    scope?: string;
  };

  // Calculate expiration
  let expiresAt: string | undefined;
  if (tokenData.expires_in) {
    expiresAt = new Date(Date.now() + tokenData.expires_in * 1000).toISOString();
  }

  // Store token
  await setConnectorToken(c.env.KV, stateData.tenantId, stateData.userId, connectorId, {
    accessToken: tokenData.access_token,
    refreshToken: tokenData.refresh_token,
    expiresAt,
    tokenType: tokenData.token_type,
    scope: tokenData.scope,
  });

  // Return success page with escaped values
  const safeConnectorName = escapeHtml(connector.name);
  const safeConnectorId = escapeHtml(connectorId);

  // Get the origin from the redirect URI stored in state for secure postMessage
  const targetOrigin = new URL(stateData.redirectUri).origin;
  const safeTargetOrigin = escapeHtml(targetOrigin);

  return c.html(`
    <html>
      <head>
        <title>OAuth Success</title>
        <style>
          body { font-family: system-ui, sans-serif; padding: 2rem; text-align: center; }
          .success { color: #22c55e; font-size: 2rem; margin-bottom: 1rem; }
        </style>
      </head>
      <body>
        <div class="success">✓</div>
        <h1>Authorization Successful</h1>
        <p>You have successfully connected ${safeConnectorName}.</p>
        <p>You can close this window now.</p>
        <script>
          // Notify parent window if in popup - use specific origin instead of wildcard
          if (window.opener) {
            window.opener.postMessage({ type: 'oauth_success', connectorId: '${safeConnectorId}' }, '${safeTargetOrigin}');
            window.close();
          }
        </script>
      </body>
    </html>
  `);
});

export { app as callbackRoute };
