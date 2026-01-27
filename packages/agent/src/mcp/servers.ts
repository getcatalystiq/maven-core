/**
 * MCP Server configuration builder
 */

import type { ConnectorMetadata } from '@maven/shared';

// MCP Server configuration types
export interface StdioMcpConfig {
  type: 'stdio';
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

export interface SseMcpConfig {
  type: 'sse';
  url: string;
  headers?: Record<string, string>;
}

export interface HttpMcpConfig {
  type: 'http';
  url: string;
  headers?: Record<string, string>;
}

export type McpServerConfig = StdioMcpConfig | SseMcpConfig | HttpMcpConfig;

/**
 * Build MCP server configurations from connector metadata
 */
export function buildMcpServers(
  connectors: ConnectorMetadata[]
): Record<string, McpServerConfig> {
  const servers: Record<string, McpServerConfig> = {};

  for (const connector of connectors) {
    const config = buildServerConfig(connector);
    if (config) {
      servers[connector.name] = config;
    }
  }

  return servers;
}

/**
 * Build a single MCP server configuration
 */
function buildServerConfig(connector: ConnectorMetadata): McpServerConfig | null {
  switch (connector.type) {
    case 'stdio':
      if (!connector.config.command) {
        return null;
      }
      return {
        type: 'stdio',
        command: connector.config.command,
        args: connector.config.args,
        env: connector.config.env,
      };

    case 'sse':
      if (!connector.config.url) {
        return null;
      }
      return {
        type: 'sse',
        url: connector.config.url,
        headers: buildHeaders(connector),
      };

    case 'http':
      if (!connector.config.url) {
        return null;
      }
      return {
        type: 'http',
        url: connector.config.url,
        headers: buildHeaders(connector),
      };

    default:
      return null;
  }
}

/**
 * Build headers with authorization if token is available
 */
function buildHeaders(connector: ConnectorMetadata): Record<string, string> {
  const headers: Record<string, string> = {
    ...connector.config.headers,
  };

  if (connector.accessToken) {
    headers['Authorization'] = `Bearer ${connector.accessToken}`;
  }

  return headers;
}

/**
 * Parse connector configuration from environment
 */
export function parseConnectorsFromEnv(): ConnectorMetadata[] {
  const configStr = process.env.CONNECTORS_CONFIG;
  if (!configStr) {
    return [];
  }

  try {
    return JSON.parse(configStr);
  } catch {
    console.error('Failed to parse CONNECTORS_CONFIG');
    return [];
  }
}
