# Authentication Guide

Maven-core supports two authentication modes: built-in and OIDC.

## Built-in Authentication

Built-in auth provides password-based authentication with JWT tokens.

### Configuration

```yaml
auth:
  mode: builtin
  builtin:
    password:
      min_length: 12
      require_special: true
    jwt:
      secret: ${JWT_SECRET}
      expiry_minutes: 15
      refresh_expiry_days: 30
```

### Password Requirements

- Minimum 12 characters (configurable)
- Optional special character requirement
- Passwords are hashed using argon2id

### JWT Tokens

- Access tokens expire after 15 minutes (configurable)
- Refresh tokens expire after 30 days (configurable)
- Tokens contain user ID, roles, and tenant ID

### API Endpoints

```bash
# Register new user
POST /auth/register
{
  "email": "user@example.com",
  "password": "secure-password-123!"
}

# Login
POST /auth/login
{
  "email": "user@example.com",
  "password": "secure-password-123!"
}
# Returns: { "access_token": "...", "refresh_token": "..." }

# Refresh token
POST /auth/refresh
{
  "refresh_token": "..."
}
# Returns: { "access_token": "..." }
```

### Using Tokens

Include the access token in the Authorization header:

```bash
curl -X POST http://localhost:8080/chat \
  -H "Authorization: Bearer eyJhbGc..." \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}'
```

## OIDC Authentication

OIDC mode validates tokens from external identity providers.

### Configuration

```yaml
auth:
  mode: oidc
  oidc:
    issuer: https://auth.example.com
    audience: maven-core
    jwks_uri: https://auth.example.com/.well-known/jwks.json
```

### Supported Providers

Maven-core works with any OIDC-compliant provider:

- Auth0
- Clerk
- Okta
- AWS Cognito
- Google Cloud Identity

### Token Validation

Maven-core validates:

- Token signature using JWKS
- Expiration (`exp` claim)
- Issuer (`iss` claim)
- Audience (`aud` claim)
- Not-before time (`nbf` claim, if present)

### User Claims

User information is extracted from JWT claims:

```python
# Available in request.state after authentication
request.state.user_id  # From 'sub' or 'user_id' claim
request.state.roles    # From 'roles' claim (array)
request.state.user     # Full decoded token
```

## RBAC (Role-Based Access Control)

### Default Roles

```yaml
rbac:
  default_role: user
  roles:
    - admin
    - user
    - service
```

### Assigning Roles

Roles are stored in the database and assigned per user:

```sql
-- Assign admin role to a user
INSERT INTO user_roles (id, tenant_id, user_id, role_id)
VALUES ('ur-1', 'tenant-123', 'user-456', 'role-admin');
```

### Skill Access Control

Skills can be restricted by role using YAML frontmatter:

```yaml
---
name: admin-tools
description: Administrative tools
allowed_roles:
  - admin
---

# Admin Tools

This skill is only available to admins.
```

### Checking Permissions

Use the PermissionManager to check permissions:

```python
from maven_core.rbac import PermissionManager

pm = PermissionManager(db)
can_access = await pm.can_access_skill(
    tenant_id="tenant-123",
    user_id="user-456",
    skill_slug="admin-tools",
)
```

## Security Best Practices

1. **Use strong JWT secrets** - At least 32 bytes of random data
2. **Set short token expiration** - 15 minutes for access tokens
3. **Rotate secrets regularly** - Change JWT secrets periodically
4. **Use HTTPS** - Always encrypt traffic in production
5. **Validate all inputs** - Never trust user-provided data
6. **Log authentication events** - Track login attempts

## Middleware

Authentication is handled by middleware:

```python
from maven_core.server import AuthenticationMiddleware

# Applied automatically when using create_app()
app.add_middleware(
    AuthenticationMiddleware,
    auth_manager=auth_manager,
    public_paths=["/health", "/ping"],
)
```

Public paths skip authentication:

- `/health` - Health check
- `/ping` - Ping endpoint
- `/oauth/callback` - OAuth callback
