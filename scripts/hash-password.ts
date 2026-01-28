#!/usr/bin/env npx tsx
/**
 * Hash a password using the shared library
 * Usage: npx tsx scripts/hash-password.ts <password>
 */

import { hashPassword } from '../packages/shared/src/crypto/password';

const password = process.argv[2];
if (!password) {
  console.error('Usage: npx tsx scripts/hash-password.ts <password>');
  process.exit(1);
}

(async () => {
  const hash = await hashPassword(password);
  console.log(hash);
})();
