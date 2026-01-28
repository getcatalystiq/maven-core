/**
 * Cloudflare Secrets Store utilities
 *
 * Provides a unified interface for accessing secrets that works with both:
 * - Local development: secrets are plain strings from .dev.vars
 * - Production: secrets are SecretBinding objects from Secrets Store
 *
 * @see https://developers.cloudflare.com/secrets-store/integrations/workers/
 */

/**
 * Cloudflare Secrets Store binding interface
 * In production, secrets are accessed via async get() method
 */
export interface SecretBinding {
  get(): Promise<string>;
}

/**
 * Union type for secrets that can be either:
 * - string: Local development (from .dev.vars)
 * - SecretBinding: Production (from Secrets Store)
 */
export type Secret = string | SecretBinding;

/**
 * Type guard to check if a value is a SecretBinding
 */
function isSecretBinding(value: Secret): value is SecretBinding {
  return typeof value === 'object' && value !== null && 'get' in value && typeof value.get === 'function';
}

/**
 * Get the secret value from either a string or SecretBinding
 *
 * @example
 * // In middleware or route handler:
 * const publicKey = await getSecret(env.JWT_PUBLIC_KEY);
 * const payload = await verifyToken(token, publicKey, env.JWT_ISSUER);
 *
 * @param secret - Either a plain string (local dev) or SecretBinding (production)
 * @returns The secret value as a string
 */
export async function getSecret(secret: Secret): Promise<string> {
  if (isSecretBinding(secret)) {
    return secret.get();
  }
  return secret;
}

/**
 * Get multiple secrets in parallel
 *
 * @example
 * const [publicKey, privateKey] = await getSecrets([env.JWT_PUBLIC_KEY, env.JWT_PRIVATE_KEY]);
 *
 * @param secrets - Array of secrets to resolve
 * @returns Array of secret values
 */
export async function getSecrets(secrets: Secret[]): Promise<string[]> {
  return Promise.all(secrets.map(getSecret));
}
