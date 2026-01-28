/**
 * Widget-specific types for the maven-widget frontend
 */

/**
 * Connector representation for widget display
 * Includes user-specific connection status
 */
export interface WidgetConnector {
  id: string;
  name: string;
  description: string | null;
  mcpServerUrl: string | null;
  requiresOauth: boolean;
  connected: boolean;
  expiresAt: string | null;
}

/**
 * Response from GET /widget/connectors
 */
export interface WidgetConnectorListResponse {
  connectors: WidgetConnector[];
}

/**
 * Response from POST /widget/connectors/:id/oauth/initiate
 */
export interface OAuthInitiateResponse {
  authorizationUrl: string;
}

/**
 * Response from POST /widget/connectors/:id/disconnect
 */
export interface DisconnectResponse {
  disconnected: boolean;
}
