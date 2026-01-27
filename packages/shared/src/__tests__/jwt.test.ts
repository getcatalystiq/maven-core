/**
 * JWT utility tests
 */

import { describe, it, expect, beforeAll } from 'vitest';
import {
  createAccessToken,
  createRefreshToken,
  createTokenPair,
  verifyToken,
  decodeToken,
  isTokenExpired,
  getJWKS,
} from '../crypto/jwt';

describe('JWT utilities', () => {
  // Test key pair (RSA 2048)
  const privateKey = `-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7o5IH/+L7qPSI
B8w6cNX3G6UjTy+aFTJjPvn0M0PF0P1qYbOG0VqMZ0zLMjHzlYKqTl1xmPlJw7KB
mxXC8l5nF8a7v0HxnzYZGqzm7E7nxHbOZz6oL0YxJLNpC3qGw8Ef3M0+y4RGdB5O
s6P2gG0CJFN3BNjJ8EzjHcPJzDCJO8a0w1vLGGZL9ZnNqnzJiQV7EsQgZ3FH0+yG
CaX7KLo0Z1JJT7YnG4D0fQE3V0E/9G4K7EG7EuF6J/rK3K7lX8p7gPy8l2UG0a5X
kKJ3EpTpX7BqSJ8t0SZG0l0g3G/k7q0g7q0g7q0g7q0g7q0g7q0g7q0g7q0g7q0g
7q0g7q0gAgMBAAECggEABE3xP8y6P8c7O0z7gP3K2CL6gP3K2CL6gP3K2CL6gP3K
2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K
2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K
2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K
2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K
2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gQKBgQDvBv3K2CL6gP3K2CL6gP3K
2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K
2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K
2CL6gP3K2CL6gP3K2CL6gQKBgQDJq3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2
CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2
CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2
CL6gP3K2CL6gQKBgBvK2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6g
P3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6g
P3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6g
P3K2CL6gQKBgHK2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2C
L6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2C
L6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2C
L6gQKBgCL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2C
L6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2C
L6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2CL6gP3K2C
L6g=
-----END PRIVATE KEY-----`;

  const publicKey = `-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu6OSB//i+6j0iAfMOnDV
9xulI08vmhUyYz759DNDxdD9amGzhtFajGdMyzIx85WCqk5dcZj5ScOygZsVwvJe
ZxfGu79B8Z82GRqs5uxO58R2zmc+qC9GMSSzaQt6hsPBH9zNPsuERnQeTrOj9oBt
AiRTdwTYyfBM4x3Dycwwi TvGtMNbyxhmS/WZzap8yYkFexLEIGdxR9PshgmL+yi6
NGdSSU+2JxuA9H0BN1dBP/RuCuxBuxLheif6ytyu5V/Ke4D8vJdlBtGuV5CidxKU
6V+wakifLdEmRtJdINxv5O6tIO6tIO6tIO6tIO6tIO6tIO6tIO6tIO6tIO6tIO6t
IQIDAQAB
-----END PUBLIC KEY-----`;

  const keyId = 'test-key-1';
  const issuer = 'https://test.example.com';

  describe('decodeToken', () => {
    it('should decode a valid token without verification', () => {
      // Create a simple test token
      const header = btoa(JSON.stringify({ alg: 'RS256', kid: keyId }));
      const payload = btoa(
        JSON.stringify({
          sub: 'user-123',
          tenant_id: 'tenant-1',
          roles: ['user'],
          iat: Math.floor(Date.now() / 1000),
          exp: Math.floor(Date.now() / 1000) + 3600,
        })
      );
      const signature = 'fake-signature';
      const token = `${header}.${payload}.${signature}`;

      const decoded = decodeToken(token);

      expect(decoded).toBeDefined();
      expect(decoded?.sub).toBe('user-123');
      expect(decoded?.tenant_id).toBe('tenant-1');
      expect(decoded?.roles).toEqual(['user']);
    });

    it('should return null for invalid tokens', () => {
      expect(decodeToken('invalid')).toBeNull();
      expect(decodeToken('')).toBeNull();
    });
  });

  describe('isTokenExpired', () => {
    it('should return true for expired tokens', () => {
      const header = btoa(JSON.stringify({ alg: 'RS256' }));
      const payload = btoa(
        JSON.stringify({
          sub: 'user-123',
          exp: Math.floor(Date.now() / 1000) - 3600, // 1 hour ago
        })
      );
      const token = `${header}.${payload}.signature`;

      expect(isTokenExpired(token)).toBe(true);
    });

    it('should return false for valid tokens', () => {
      const header = btoa(JSON.stringify({ alg: 'RS256' }));
      const payload = btoa(
        JSON.stringify({
          sub: 'user-123',
          exp: Math.floor(Date.now() / 1000) + 3600, // 1 hour from now
        })
      );
      const token = `${header}.${payload}.signature`;

      expect(isTokenExpired(token)).toBe(false);
    });

    it('should return true for invalid tokens', () => {
      expect(isTokenExpired('invalid')).toBe(true);
    });
  });
});
