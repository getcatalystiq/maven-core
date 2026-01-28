/**
 * Connectors service - manages MCP server configurations and OAuth tokens
 */

import type {
  Connector,
  ConnectorToken,
  ConnectorConfig,
  OAuthServerMetadata,
  HttpConfig,
} from '@maven/shared';

// Environment type for redirect validation
interface EnvWithCors {
  CORS_ALLOWED_ORIGINS?: string;
}

/**
 * Validate redirect URI against allowed origins
 * Uses CORS_ALLOWED_ORIGINS env var or defaults to common development origins
 */
export function validateRedirectUri(env: EnvWithCors, redirectUri: string): boolean {
  try {
    const redirectUrl = new URL(redirectUri);
    const redirectOrigin = redirectUrl.origin;

    // Default allowed origins for development
    const defaultOrigins = [
      'http://localhost:8787',
      'http://localhost:8788',
      'http://127.0.0.1:8787',
      'http://127.0.0.1:8788',
    ];

    // Parse configured origins or use defaults
    const allowedOriginsStr = env.CORS_ALLOWED_ORIGINS || '';
    const configuredOrigins = allowedOriginsStr
      ? allowedOriginsStr.split(',').map((o) => o.trim()).filter(Boolean)
      : [];

    const allowedOrigins = configuredOrigins.length > 0
      ? configuredOrigins
      : defaultOrigins;

    return allowedOrigins.includes(redirectOrigin);
  } catch {
    return false;
  }
}

/**
 * Discover OAuth endpoints from MCP server's well-known configuration
 * Per RFC 8414: https://datatracker.ietf.org/doc/html/rfc8414
 */
export async function discoverOAuthEndpoints(
  mcpServerUrl: string
): Promise<OAuthServerMetadata | null> {
  try {
    const wellKnownUrl = new URL('/.well-known/oauth-authorization-server', mcpServerUrl);

    // Add timeout to prevent hanging on slow servers
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const response = await fetch(wellKnownUrl.toString(), {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      console.log(`No OAuth discovery at ${wellKnownUrl}: ${response.status}`);
      return null;
    }

    const metadata = (await response.json()) as OAuthServerMetadata;

    // Validate required fields per RFC 8414
    if (!metadata.authorization_endpoint || !metadata.token_endpoint) {
      console.error('OAuth metadata missing required endpoints');
      return null;
    }

    return metadata;
  } catch (error) {
    console.error('OAuth discovery failed:', error);
    return null;
  }
}

/**
 * Discover OAuth endpoints with KV caching (1 hour TTL)
 * Reduces latency for repeated OAuth initiations
 */
export async function discoverOAuthEndpointsCached(
  kv: KVNamespace,
  mcpServerUrl: string
): Promise<OAuthServerMetadata | null> {
  const cacheKey = `oauth_discovery:${mcpServerUrl}`;

  // Check cache first
  const cached = await kv.get<OAuthServerMetadata>(cacheKey, 'json');
  if (cached) {
    return cached;
  }

  // Fetch fresh metadata
  const metadata = await discoverOAuthEndpoints(mcpServerUrl);
  if (metadata) {
    // Cache for 1 hour
    await kv.put(cacheKey, JSON.stringify(metadata), { expirationTtl: 3600 });
  }

  return metadata;
}

/**
 * Get MCP server URL from connector config
 */
export function getMcpServerUrl(connector: Connector): string | null {
  const config = connector.config;
  if (config.type === 'http' || config.type === 'sse') {
    return (config as HttpConfig).url;
  }
  return null;
}

// Connector operations
export async function createConnector(
  db: D1Database,
  connector: Omit<Connector, 'createdAt'>
): Promise<Connector> {
  const now = new Date().toISOString();

  await db
    .prepare(
      `INSERT INTO connectors (id, tenant_id, name, description, type, config, oauth_client_id, oauth_scopes, enabled, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .bind(
      connector.id,
      connector.tenantId,
      connector.name,
      connector.description || null,
      connector.type,
      JSON.stringify(connector.config),
      connector.oauthClientId || null,
      connector.oauthScopes ? JSON.stringify(connector.oauthScopes) : null,
      connector.enabled ? 1 : 0,
      now
    )
    .run();

  return { ...connector, createdAt: now };
}

export async function getConnectorById(db: D1Database, id: string): Promise<Connector | null> {
  const row = await db
    .prepare('SELECT * FROM connectors WHERE id = ?')
    .bind(id)
    .first<ConnectorRow>();

  return row ? rowToConnector(row) : null;
}

export async function getConnectorByName(
  db: D1Database,
  tenantId: string,
  name: string
): Promise<Connector | null> {
  const row = await db
    .prepare('SELECT * FROM connectors WHERE tenant_id = ? AND name = ?')
    .bind(tenantId, name)
    .first<ConnectorRow>();

  return row ? rowToConnector(row) : null;
}

export async function listConnectors(
  db: D1Database,
  tenantId: string,
  offset = 0,
  limit = 20
): Promise<{ connectors: Connector[]; total: number }> {
  const [connectorsResult, countResult] = await Promise.all([
    db
      .prepare(
        'SELECT * FROM connectors WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?'
      )
      .bind(tenantId, limit, offset)
      .all<ConnectorRow>(),
    db
      .prepare('SELECT COUNT(*) as count FROM connectors WHERE tenant_id = ?')
      .bind(tenantId)
      .first<{ count: number }>(),
  ]);

  return {
    connectors: connectorsResult.results.map(rowToConnector),
    total: countResult?.count || 0,
  };
}

export async function listEnabledConnectors(
  db: D1Database,
  tenantId: string
): Promise<Connector[]> {
  const result = await db
    .prepare('SELECT * FROM connectors WHERE tenant_id = ? AND enabled = 1')
    .bind(tenantId)
    .all<ConnectorRow>();

  return result.results.map(rowToConnector);
}

export async function updateConnector(
  db: D1Database,
  id: string,
  updates: Partial<Pick<Connector, 'name' | 'description' | 'config' | 'oauthScopes' | 'enabled'>>
): Promise<void> {
  const setClauses: string[] = [];
  const values: (string | number | null)[] = [];

  if (updates.name !== undefined) {
    setClauses.push('name = ?');
    values.push(updates.name);
  }
  if (updates.description !== undefined) {
    setClauses.push('description = ?');
    values.push(updates.description);
  }
  if (updates.config !== undefined) {
    setClauses.push('config = ?');
    values.push(JSON.stringify(updates.config));
  }
  if (updates.oauthScopes !== undefined) {
    setClauses.push('oauth_scopes = ?');
    values.push(JSON.stringify(updates.oauthScopes));
  }
  if (updates.enabled !== undefined) {
    setClauses.push('enabled = ?');
    values.push(updates.enabled ? 1 : 0);
  }

  if (setClauses.length === 0) return;

  values.push(id);

  await db
    .prepare(`UPDATE connectors SET ${setClauses.join(', ')} WHERE id = ?`)
    .bind(...values)
    .run();
}

export async function deleteConnector(db: D1Database, id: string): Promise<void> {
  await db.prepare('DELETE FROM connectors WHERE id = ?').bind(id).run();
}

// Token operations (stored in KV)
export async function getConnectorToken(
  kv: KVNamespace,
  tenantId: string,
  userId: string,
  connectorId: string
): Promise<ConnectorToken | null> {
  const key = `connector:${tenantId}:${userId}:${connectorId}`;
  return kv.get<ConnectorToken>(key, 'json');
}

export async function setConnectorToken(
  kv: KVNamespace,
  tenantId: string,
  userId: string,
  connectorId: string,
  token: ConnectorToken
): Promise<void> {
  const key = `connector:${tenantId}:${userId}:${connectorId}`;

  // Calculate TTL based on expiration
  let expirationTtl: number | undefined;
  if (token.expiresAt) {
    const expiresIn = Math.floor((new Date(token.expiresAt).getTime() - Date.now()) / 1000);
    // Add some buffer for refresh token operations
    expirationTtl = Math.max(expiresIn + 86400, 3600); // At least 1 hour, max 1 day after expiry
  }

  await kv.put(key, JSON.stringify(token), { expirationTtl });
}

export async function deleteConnectorToken(
  kv: KVNamespace,
  tenantId: string,
  userId: string,
  connectorId: string
): Promise<void> {
  const key = `connector:${tenantId}:${userId}:${connectorId}`;
  await kv.delete(key);
}

// OAuth state operations
export interface OAuthStateData {
  connectorId: string;
  tenantId: string;
  userId: string;
  redirectUri: string;
  nonce: string;
  codeVerifier?: string;       // PKCE code verifier
  tokenEndpoint: string;       // Discovered token endpoint
}

export async function setOAuthState(
  kv: KVNamespace,
  state: string,
  data: OAuthStateData
): Promise<void> {
  const key = `oauth_state:${state}`;
  await kv.put(key, JSON.stringify(data), { expirationTtl: 600 }); // 10 minute TTL
}

export async function getOAuthState(
  kv: KVNamespace,
  state: string
): Promise<OAuthStateData | null> {
  const key = `oauth_state:${state}`;
  return kv.get(key, 'json');
}

export async function deleteOAuthState(kv: KVNamespace, state: string): Promise<void> {
  const key = `oauth_state:${state}`;
  await kv.delete(key);
}

// Store OAuth client secrets securely
export async function setConnectorSecret(
  kv: KVNamespace,
  connectorId: string,
  clientSecret: string
): Promise<void> {
  const key = `connector_secret:${connectorId}`;
  await kv.put(key, clientSecret);
}

export async function getConnectorSecret(
  kv: KVNamespace,
  connectorId: string
): Promise<string | null> {
  const key = `connector_secret:${connectorId}`;
  return kv.get(key);
}

export async function deleteConnectorSecret(
  kv: KVNamespace,
  connectorId: string
): Promise<void> {
  const key = `connector_secret:${connectorId}`;
  await kv.delete(key);
}

/**
 * Delete all tokens for a connector (across all users)
 * Note: This is best-effort since we can't list all users with tokens
 */
export async function deleteAllConnectorTokens(
  kv: KVNamespace,
  tenantId: string,
  connectorId: string
): Promise<void> {
  // List all keys with the connector prefix pattern
  // Note: This lists keys with a prefix, which is the best we can do in KV
  const prefix = `connector:${tenantId}:`;
  const list = await kv.list({ prefix });

  // Filter and delete keys that end with the connector ID
  const deletePromises = list.keys
    .filter((key) => key.name.endsWith(`:${connectorId}`))
    .map((key) => kv.delete(key.name));

  await Promise.all(deletePromises);
}

/**
 * Delete all tokens for a user (across all connectors)
 */
export async function deleteAllUserTokens(
  kv: KVNamespace,
  tenantId: string,
  userId: string
): Promise<void> {
  // List all keys with the user prefix pattern
  const prefix = `connector:${tenantId}:${userId}:`;
  const list = await kv.list({ prefix });

  const deletePromises = list.keys.map((key) => kv.delete(key.name));
  await Promise.all(deletePromises);
}

// Row types and converters
interface ConnectorRow {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  type: string;
  config: string;
  oauth_client_id: string | null;
  oauth_scopes: string | null;
  enabled: number;
  created_at: string;
}

function rowToConnector(row: ConnectorRow): Connector {
  return {
    id: row.id,
    tenantId: row.tenant_id,
    name: row.name,
    description: row.description || undefined,
    type: row.type as Connector['type'],
    config: JSON.parse(row.config) as ConnectorConfig,
    oauthClientId: row.oauth_client_id || undefined,
    oauthScopes: row.oauth_scopes ? JSON.parse(row.oauth_scopes) : undefined,
    enabled: row.enabled === 1,
    createdAt: row.created_at,
  };
}
