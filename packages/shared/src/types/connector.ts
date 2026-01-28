/**
 * MCP Connector types
 */

export interface Connector {
  id: string;
  tenantId: string;
  name: string;
  description?: string;        // Human-readable description for widget display
  type: ConnectorType;
  config: ConnectorConfig;
  oauthClientId?: string;      // OAuth client ID (discovery via MCP server URL)
  oauthScopes?: string[];      // Custom scopes (optional, uses discovered defaults)
  enabled: boolean;
  createdAt: string;
}

export type ConnectorType = 'stdio' | 'sse' | 'http';

export type ConnectorConfig = StdioConfig | SseConfig | HttpConfig;

export interface StdioConfig {
  type: 'stdio';
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

export interface SseConfig {
  type: 'sse';
  url: string;
  headers?: Record<string, string>;
}

export interface HttpConfig {
  type: 'http';
  url: string;
  headers?: Record<string, string>;
}

export interface ConnectorToken {
  accessToken: string;
  refreshToken?: string;
  expiresAt?: string;
  tokenType?: string;
  scope?: string;
}

export interface ConnectorCreateRequest {
  name: string;
  description?: string;        // Human-readable description
  type: ConnectorType;
  config: ConnectorConfig;
  oauthClientId?: string;      // OAuth client ID
  oauthClientSecret?: string;  // OAuth client secret (stored securely in KV)
  oauthScopes?: string[];      // Custom scopes (optional)
}

export interface ConnectorUpdateRequest {
  name?: string;
  description?: string;
  config?: Partial<ConnectorConfig>;
  oauthScopes?: string[];
  enabled?: boolean;
}

export interface ConnectorListResponse {
  connectors: Connector[];
  total: number;
  offset: number;
  limit: number;
}

export interface OAuthState {
  connectorId: string;
  tenantId: string;
  userId: string;
  redirectUri: string;
  nonce: string;
  codeVerifier?: string;       // PKCE code verifier
  tokenEndpoint: string;       // Discovered token endpoint
}

/**
 * OAuth 2.0 Authorization Server Metadata (RFC 8414)
 * https://datatracker.ietf.org/doc/html/rfc8414
 */
export interface OAuthServerMetadata {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  scopes_supported?: string[];
  response_types_supported?: string[];
  code_challenge_methods_supported?: string[];
  token_endpoint_auth_methods_supported?: string[];
}
