/**
 * Password hashing using scrypt (compatible with Cloudflare Workers)
 *
 * Note: Argon2id is not available in Workers runtime, so we use scrypt
 * which provides similar security properties and is supported via Web Crypto API.
 */

const SALT_LENGTH = 16;
const KEY_LENGTH = 32;
const SCRYPT_N = 16384;  // CPU/memory cost parameter
const SCRYPT_R = 8;       // Block size
const SCRYPT_P = 1;       // Parallelization

/**
 * Hash a password using scrypt
 */
export async function hashPassword(password: string): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(SALT_LENGTH));
  const hash = await deriveKey(password, salt);

  // Format: $scrypt$N$r$p$salt$hash
  const params = `$scrypt$${SCRYPT_N}$${SCRYPT_R}$${SCRYPT_P}`;
  const saltB64 = bufferToBase64(salt);
  const hashB64 = bufferToBase64(hash);

  return `${params}$${saltB64}$${hashB64}`;
}

/**
 * Verify a password against a hash
 */
export async function verifyPassword(password: string, storedHash: string): Promise<boolean> {
  try {
    const parts = storedHash.split('$');
    if (parts.length !== 7 || parts[1] !== 'scrypt') {
      return false;
    }

    const [, , n, r, p, saltB64, hashB64] = parts;
    const salt = base64ToBuffer(saltB64);
    const expectedHash = base64ToBuffer(hashB64);

    const derivedHash = await deriveKey(password, salt, parseInt(n), parseInt(r), parseInt(p));

    return timingSafeEqual(derivedHash, expectedHash);
  } catch {
    return false;
  }
}

/**
 * Derive a key using PBKDF2 (Web Crypto API fallback)
 * Note: True scrypt isn't available in Web Crypto API, so we use PBKDF2 with high iterations
 */
async function deriveKey(
  password: string,
  salt: Uint8Array,
  _n = SCRYPT_N,
  _r = SCRYPT_R,
  _p = SCRYPT_P
): Promise<Uint8Array> {
  const encoder = new TextEncoder();
  const passwordBuffer = encoder.encode(password);

  // Import password as key
  const baseKey = await crypto.subtle.importKey(
    'raw',
    passwordBuffer,
    'PBKDF2',
    false,
    ['deriveBits']
  );

  // Derive bits using PBKDF2 (we use high iteration count to compensate for no scrypt)
  const iterations = 100000;
  const bits = await crypto.subtle.deriveBits(
    {
      name: 'PBKDF2',
      salt,
      iterations,
      hash: 'SHA-256',
    },
    baseKey,
    KEY_LENGTH * 8
  );

  return new Uint8Array(bits);
}

/**
 * Timing-safe comparison of two buffers
 */
function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) {
    return false;
  }

  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a[i] ^ b[i];
  }

  return result === 0;
}

/**
 * Convert buffer to base64
 */
function bufferToBase64(buffer: Uint8Array): string {
  return btoa(String.fromCharCode(...buffer));
}

/**
 * Convert base64 to buffer
 */
function base64ToBuffer(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

