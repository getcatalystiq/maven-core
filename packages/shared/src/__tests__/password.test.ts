/**
 * Password utility tests
 */

import { describe, it, expect } from 'vitest';
import { hashPassword, verifyPassword } from '../crypto/password';

describe('Password utilities', () => {
  describe('hashPassword', () => {
    it('should generate a hash in the correct format', async () => {
      const hash = await hashPassword('TestPassword123!');

      expect(hash).toBeDefined();
      expect(hash.startsWith('$scrypt$')).toBe(true);

      // Should have format: $scrypt$N$r$p$salt$hash
      const parts = hash.split('$');
      expect(parts.length).toBe(7);
      expect(parts[1]).toBe('scrypt');
    });

    it('should generate different hashes for the same password', async () => {
      const hash1 = await hashPassword('TestPassword123!');
      const hash2 = await hashPassword('TestPassword123!');

      expect(hash1).not.toBe(hash2);
    });
  });

  describe('verifyPassword', () => {
    it('should verify correct password', async () => {
      const password = 'TestPassword123!';
      const hash = await hashPassword(password);

      const result = await verifyPassword(password, hash);
      expect(result).toBe(true);
    });

    it('should reject incorrect password', async () => {
      const hash = await hashPassword('TestPassword123!');

      const result = await verifyPassword('WrongPassword123!', hash);
      expect(result).toBe(false);
    });

    it('should reject invalid hash format', async () => {
      const result = await verifyPassword('TestPassword123!', 'invalid-hash');
      expect(result).toBe(false);
    });
  });

});
