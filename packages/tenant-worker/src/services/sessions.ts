/**
 * Session persistence service
 *
 * Handles session metadata in KV and message history in R2.
 * Uses Result pattern for explicit error handling.
 */

import type { SessionMetadata } from '@maven/shared';

/**
 * Result type for session lookup - explicit error handling
 * Returns 'unauthorized' error for wrong owner (caller converts to 404 for security)
 */
export type SessionLookupResult =
  | { ok: true; metadata: SessionMetadata | null }  // null = new session
  | { ok: false; error: 'unauthorized' };

/**
 * Build the KV key for a session
 */
export function getSessionKey(tenantId: string, sessionId: string): string {
  return `session:${tenantId}:${sessionId}`;
}

/**
 * Get session metadata with ownership validation
 *
 * SECURITY: Returns 'unauthorized' error for wrong owner.
 * Caller MUST convert to 404 (same as not found) to prevent enumeration attacks.
 *
 * @param kv - KV namespace binding
 * @param tenantId - Tenant ID
 * @param sessionId - Session ID (UUID)
 * @param userId - User ID making the request
 * @returns Result with metadata (null if new session) or unauthorized error
 */
export async function getSessionForUser(
  kv: KVNamespace,
  tenantId: string,
  sessionId: string,
  userId: string
): Promise<SessionLookupResult> {
  const key = getSessionKey(tenantId, sessionId);

  try {
    const metadata = await kv.get<SessionMetadata>(key, 'json');

    // SECURITY: Return error for wrong owner (caller converts to 404)
    if (metadata && metadata.userId !== userId) {
      return { ok: false, error: 'unauthorized' };
    }

    // Return metadata (or null for new session)
    return { ok: true, metadata };
  } catch (error) {
    // KV error - log and treat as new session for resilience
    console.error(`[Sessions] KV error fetching ${key}:`, error);
    return { ok: true, metadata: null };
  }
}

/**
 * Create or update session metadata
 *
 * @param kv - KV namespace binding
 * @param tenantId - Tenant ID
 * @param sessionId - Session ID (UUID)
 * @param metadata - Session metadata to store
 * @param ttlSeconds - TTL in seconds (default: 90 days)
 */
export async function putSessionMetadata(
  kv: KVNamespace,
  tenantId: string,
  sessionId: string,
  metadata: SessionMetadata,
  ttlSeconds: number
): Promise<void> {
  const key = getSessionKey(tenantId, sessionId);

  await kv.put(key, JSON.stringify(metadata), {
    expirationTtl: ttlSeconds,
  });
}

/**
 * Build R2 path for message history batch file
 *
 * Uses timestamped batch files for O(1) write performance:
 * sessions/{tenantId}/{sessionId}/{timestamp}.ndjson
 */
export function getHistoryPath(tenantId: string, sessionId: string, timestamp: number): string {
  return `sessions/${tenantId}/${sessionId}/${timestamp}.ndjson`;
}
