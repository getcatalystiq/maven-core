/**
 * JWT utilities using RS256 asymmetric signing
 */

import {
  SignJWT,
  jwtVerify,
  importPKCS8,
  importSPKI,
  exportJWK,
  exportPKCS8 as joseExportPKCS8,
  exportSPKI as joseExportSPKI,
  generateKeyPair,
  type KeyLike,
} from 'jose';
import type { JWTPayload, TokenPair } from '../types/auth';

const ALG = 'RS256';

/**
 * Cache for imported keys to avoid re-importing on every operation
 */
const keyCache = new Map<string, { key: KeyLike; timestamp: number }>();
const KEY_CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

/**
 * Get a cached public key or import it
 */
async function getCachedPublicKey(publicKey: string): Promise<KeyLike> {
  const cacheKey = `pub:${publicKey.slice(0, 50)}`; // Use first 50 chars as cache key
  const now = Date.now();

  const cached = keyCache.get(cacheKey);
  if (cached && now - cached.timestamp < KEY_CACHE_TTL_MS) {
    return cached.key;
  }

  const key = await importSPKI(publicKey, ALG, { extractable: true });
  keyCache.set(cacheKey, { key, timestamp: now });

  // Cleanup old entries periodically
  if (keyCache.size > 10) {
    for (const [k, v] of keyCache.entries()) {
      if (now - v.timestamp > KEY_CACHE_TTL_MS) {
        keyCache.delete(k);
      }
    }
  }

  return key;
}

/**
 * Get a cached private key or import it
 */
async function getCachedPrivateKey(privateKey: string): Promise<KeyLike> {
  const cacheKey = `priv:${privateKey.slice(0, 50)}`; // Use first 50 chars as cache key
  const now = Date.now();

  const cached = keyCache.get(cacheKey);
  if (cached && now - cached.timestamp < KEY_CACHE_TTL_MS) {
    return cached.key;
  }

  const key = await importPKCS8(privateKey, ALG);
  keyCache.set(cacheKey, { key, timestamp: now });

  return key;
}

/**
 * Generate a new RS256 key pair
 */
export async function generateKeyPairPEM(): Promise<{ privateKey: string; publicKey: string }> {
  const { privateKey, publicKey } = await generateKeyPair(ALG, {
    extractable: true,
  });

  // Export as PEM format using jose's built-in exporters
  const privateKeyPEM = await joseExportPKCS8(privateKey);
  const publicKeyPEM = await joseExportSPKI(publicKey);

  return {
    privateKey: privateKeyPEM,
    publicKey: publicKeyPEM,
  };
}

/**
 * Create an access token
 */
export async function createAccessToken(
  userId: string,
  tenantId: string | null,
  roles: string[],
  privateKey: string,
  keyId: string,
  issuer: string,
  expiryMinutes = 15
): Promise<string> {
  const key = await getCachedPrivateKey(privateKey);

  return new SignJWT({
    sub: userId,
    tenant_id: tenantId,
    roles,
  })
    .setProtectedHeader({ alg: ALG, kid: keyId })
    .setIssuer(issuer)
    .setIssuedAt()
    .setExpirationTime(`${expiryMinutes}m`)
    .sign(key);
}

/**
 * Create a refresh token (longer-lived)
 */
export async function createRefreshToken(
  userId: string,
  tenantId: string | null,
  privateKey: string,
  keyId: string,
  issuer: string,
  expiryDays = 7
): Promise<string> {
  const key = await getCachedPrivateKey(privateKey);

  return new SignJWT({
    sub: userId,
    tenant_id: tenantId,
    type: 'refresh',
  })
    .setProtectedHeader({ alg: ALG, kid: keyId })
    .setIssuer(issuer)
    .setIssuedAt()
    .setExpirationTime(`${expiryDays}d`)
    .sign(key);
}

/**
 * Create a token pair (access + refresh)
 */
export async function createTokenPair(
  userId: string,
  tenantId: string | null,
  roles: string[],
  privateKey: string,
  keyId: string,
  issuer: string,
  accessExpiryMinutes = 15,
  refreshExpiryDays = 7
): Promise<TokenPair> {
  const [accessToken, refreshToken] = await Promise.all([
    createAccessToken(userId, tenantId, roles, privateKey, keyId, issuer, accessExpiryMinutes),
    createRefreshToken(userId, tenantId, privateKey, keyId, issuer, refreshExpiryDays),
  ]);

  return {
    accessToken,
    refreshToken,
    expiresIn: accessExpiryMinutes * 60,
  };
}

/**
 * Verify a token and return the payload
 */
export async function verifyToken(
  token: string,
  publicKey: string,
  issuer: string
): Promise<JWTPayload> {
  const key = await getCachedPublicKey(publicKey);
  const { payload } = await jwtVerify(token, key, { issuer });

  return {
    sub: payload.sub as string,
    tenant_id: (payload.tenant_id as string | null) ?? null,
    roles: (payload.roles as string[]) || [],
    type: payload.type as 'access' | 'refresh' | undefined,
    iat: payload.iat as number,
    exp: payload.exp as number,
  };
}

/**
 * Decode a token without verification (for debugging)
 */
export function decodeToken(token: string): JWTPayload | null {
  try {
    const [, payloadB64] = token.split('.');
    const payload = JSON.parse(atob(payloadB64));
    return payload;
  } catch {
    return null;
  }
}

/**
 * Get JWKS (JSON Web Key Set) for public key distribution
 */
export async function getJWKS(
  publicKey: string,
  keyId: string
): Promise<{ keys: object[] }> {
  const key = await getCachedPublicKey(publicKey);
  const jwk = await exportJWK(key);

  return {
    keys: [
      {
        ...jwk,
        kid: keyId,
        alg: ALG,
        use: 'sig',
      },
    ],
  };
}

/**
 * Check if a token is expired
 */
export function isTokenExpired(token: string): boolean {
  const payload = decodeToken(token);
  if (!payload || !payload.exp) return true;
  return payload.exp * 1000 < Date.now();
}
