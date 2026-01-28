# Security Policy

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly.

### How to Report

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email security concerns to: **security@maven.example.com**

Include the following information in your report:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fixes (optional)

### What to Expect

1. **Acknowledgment**: We will acknowledge receipt of your report within 48 hours
2. **Investigation**: We will investigate and provide an initial assessment within 7 days
3. **Resolution**: We aim to resolve critical vulnerabilities within 30 days
4. **Disclosure**: We will coordinate with you on public disclosure timing

### Scope

The following are in scope for security reports:
- Authentication and authorization bypasses
- Data exposure or leakage
- Injection vulnerabilities (SQL, command, etc.)
- Cross-site scripting (XSS)
- Cross-site request forgery (CSRF)
- Insecure cryptographic practices
- Privilege escalation

### Out of Scope

- Social engineering attacks
- Denial of service attacks
- Issues in dependencies (report to the upstream project)
- Issues requiring physical access

## Security Best Practices

When deploying Maven Core:

1. **Never commit secrets** - Use environment variables or secret managers
2. **Rotate keys regularly** - JWT keys, API keys, etc.
3. **Use HTTPS** - Always use TLS in production
4. **Limit permissions** - Apply principle of least privilege
5. **Keep dependencies updated** - Regularly update npm packages

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest  | Yes       |
| < Latest | Best effort |

## Recognition

We appreciate responsible disclosure and will acknowledge security researchers in our release notes (with permission).
