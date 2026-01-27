/**
 * Security tests for controller
 */

import { describe, it, expect } from 'vitest';

// Test path traversal validation
describe('Path Traversal Protection', () => {
  function isValidPathComponent(component: string): boolean {
    if (!component) return false;
    if (component.includes('..')) return false;
    if (component.startsWith('/')) return false;
    if (component.includes('\0')) return false;
    return /^[a-zA-Z0-9_\-\.]+$/.test(component);
  }

  it('should reject path traversal attempts', () => {
    expect(isValidPathComponent('..')).toBe(false);
    expect(isValidPathComponent('../')).toBe(false);
    expect(isValidPathComponent('..\\etc')).toBe(false);
    expect(isValidPathComponent('foo/../bar')).toBe(false);
  });

  it('should reject absolute paths', () => {
    expect(isValidPathComponent('/etc/passwd')).toBe(false);
    expect(isValidPathComponent('/root')).toBe(false);
  });

  it('should reject null bytes', () => {
    expect(isValidPathComponent('file\0.txt')).toBe(false);
    expect(isValidPathComponent('\0')).toBe(false);
  });

  it('should reject special characters', () => {
    expect(isValidPathComponent('file;rm')).toBe(false);
    expect(isValidPathComponent('file|cat')).toBe(false);
    expect(isValidPathComponent('file$HOME')).toBe(false);
    expect(isValidPathComponent('file`id`')).toBe(false);
  });

  it('should accept valid path components', () => {
    expect(isValidPathComponent('myfile.txt')).toBe(true);
    expect(isValidPathComponent('SKILL.md')).toBe(true);
    expect(isValidPathComponent('my-skill')).toBe(true);
    expect(isValidPathComponent('skill_v2')).toBe(true);
    expect(isValidPathComponent('tenant123')).toBe(true);
  });

  it('should reject empty components', () => {
    expect(isValidPathComponent('')).toBe(false);
  });
});

// Test redirect URI validation
describe('Redirect URI Validation', () => {
  function validateRedirectUri(requestUrl: string, redirectUri: string): boolean {
    try {
      const requestOrigin = new URL(requestUrl).origin;
      const redirectUrl = new URL(redirectUri);
      return redirectUrl.origin === requestOrigin;
    } catch {
      return false;
    }
  }

  it('should accept same-origin redirects', () => {
    expect(validateRedirectUri(
      'https://maven.example.com/oauth/connector/authorize',
      'https://maven.example.com/oauth/connector/callback'
    )).toBe(true);
  });

  it('should reject cross-origin redirects', () => {
    expect(validateRedirectUri(
      'https://maven.example.com/oauth/connector/authorize',
      'https://evil.com/callback'
    )).toBe(false);

    expect(validateRedirectUri(
      'https://maven.example.com/oauth/connector/authorize',
      'https://maven.example.com.evil.com/callback'
    )).toBe(false);
  });

  it('should reject invalid URLs', () => {
    expect(validateRedirectUri(
      'https://maven.example.com/oauth/connector/authorize',
      'not-a-valid-url'
    )).toBe(false);

    expect(validateRedirectUri(
      'https://maven.example.com/oauth/connector/authorize',
      ''
    )).toBe(false);
  });

  it('should reject different protocols', () => {
    expect(validateRedirectUri(
      'https://maven.example.com/oauth/connector/authorize',
      'http://maven.example.com/callback'
    )).toBe(false);
  });
});

// Test HTML escaping
describe('HTML Escaping', () => {
  function escapeHtml(str: string): string {
    const htmlEscapes: Record<string, string> = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    };
    return str.replace(/[&<>"']/g, (char) => htmlEscapes[char]);
  }

  it('should escape HTML special characters', () => {
    expect(escapeHtml('<script>alert("xss")</script>')).toBe(
      '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
    );
  });

  it('should escape ampersands', () => {
    expect(escapeHtml('foo & bar')).toBe('foo &amp; bar');
  });

  it('should escape single quotes', () => {
    expect(escapeHtml("it's")).toBe("it&#39;s");
  });

  it('should handle strings without special characters', () => {
    expect(escapeHtml('Hello World')).toBe('Hello World');
  });

  it('should handle empty strings', () => {
    expect(escapeHtml('')).toBe('');
  });

  it('should escape XSS payloads', () => {
    // The key is that < and > are escaped, preventing tag creation
    const payloads = [
      { input: '<img src=x onerror=alert(1)>', shouldNotContain: ['<img', '>'] },
      { input: '"><script>alert(document.cookie)</script>', shouldNotContain: ['<script', '</script>'] },
      { input: '<svg/onload=alert(1)>', shouldNotContain: ['<svg', '>'] },
    ];

    for (const { input, shouldNotContain } of payloads) {
      const escaped = escapeHtml(input);
      for (const forbidden of shouldNotContain) {
        expect(escaped).not.toContain(forbidden);
      }
      // Verify the HTML entities are present
      if (input.includes('<')) {
        expect(escaped).toContain('&lt;');
      }
      if (input.includes('>')) {
        expect(escaped).toContain('&gt;');
      }
    }
  });
});
