/**
 * Session TTL constants for persistence
 */

/** 90 days in seconds (for KV expirationTtl) */
export const SESSION_TTL_SECONDS = 7776000 as const;

/** 90 days (for documentation / readability) */
export const SESSION_TTL_DAYS = 90 as const;
