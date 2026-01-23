# API Reference

Complete API reference for maven-core HTTP endpoints.

## Health Endpoints

### GET /health

Health check endpoint. Always returns 200 if server is running.

**Response:**
```json
{
  "status": "ok",
  "timestamp": 1706123456.789
}
```

### GET /ping

Alias for `/health`.

## Chat Endpoints

### POST /chat

Send a message and receive a JSON response.

**Request:**
```json
{
  "message": "Hello, how are you?",
  "user_id": "user-123",
  "session_id": "session-456"  // Optional
}
```

**Response:**
```json
{
  "content": "I'm doing well, thank you for asking!",
  "session_id": "session-456",
  "message_id": "msg-789"
}
```

### POST /chat/stream

Send a message and receive a streaming SSE response.

**Request:**
```json
{
  "message": "Tell me a story",
  "user_id": "user-123",
  "session_id": "session-456"  // Optional
}
```

**Response:** Server-Sent Events stream

```
event: content
data: {"chunk": "Once "}

event: content
data: {"chunk": "upon "}

event: content
data: {"chunk": "a time..."}

event: done
data: {"content": "Once upon a time...", "session_id": "session-456"}
```

### POST /invocations

AWS SageMaker-compatible alias for `/chat/stream`.

## Skills Endpoints

### GET /skills

List available skills for a user.

**Query Parameters:**
- `user_id` (optional) - Filter skills by user access

**Response:**
```json
{
  "skills": [
    {
      "slug": "code-review",
      "name": "Code Review",
      "description": "Review code for issues"
    }
  ],
  "user_id": "user-123"
}
```

## Session Endpoints

### GET /sessions

List sessions for a user.

**Query Parameters:**
- `user_id` (required) - User ID
- `limit` (optional, default 50) - Maximum results
- `offset` (optional, default 0) - Offset for pagination

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "session-123",
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:35:00Z",
      "turn_count": 5
    }
  ],
  "user_id": "user-123",
  "limit": 50,
  "offset": 0
}
```

### GET /sessions/{session_id}

Get session details including transcript.

**Query Parameters:**
- `user_id` (required) - User ID for authorization

**Response:**
```json
{
  "session_id": "session-123",
  "user_id": "user-123",
  "turns": [
    {
      "role": "user",
      "content": "Hello",
      "timestamp": "2024-01-15T10:30:00Z"
    },
    {
      "role": "assistant",
      "content": "Hi there!",
      "timestamp": "2024-01-15T10:30:01Z"
    }
  ]
}
```

## Connector Endpoints

### GET /connectors

List available connectors.

**Query Parameters:**
- `user_id` (optional) - Check connection status for user

**Response:**
```json
{
  "connectors": [
    {
      "slug": "github",
      "name": "GitHub",
      "connected": true
    }
  ],
  "user_id": "user-123"
}
```

### POST /connectors/{connector_name}/oauth/start

Start OAuth flow for a connector.

**Request:**
```json
{
  "user_id": "user-123",
  "redirect_uri": "https://app.example.com/callback"
}
```

**Response:**
```json
{
  "connector": "github",
  "authorization_url": "https://github.com/login/oauth/authorize?...",
  "state": "random-state-value"
}
```

### GET /oauth/callback

OAuth callback handler.

**Query Parameters:**
- `code` (required) - Authorization code
- `state` (required) - State for verification

**Response:**
```json
{
  "success": true,
  "message": "OAuth flow completed"
}
```

## Error Responses

All errors return a JSON object with an `error` field:

```json
{
  "error": "Missing required field: message"
}
```

### Common Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 400 | Bad request (missing/invalid parameters) |
| 401 | Unauthorized (missing/invalid auth) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not found |
| 429 | Rate limited |
| 500 | Internal server error |

## Rate Limiting

Default rate limits:
- 60 requests per minute per IP

Rate limit headers are included in responses:
- `X-RateLimit-Limit` - Maximum requests
- `X-RateLimit-Remaining` - Remaining requests
- `X-RateLimit-Reset` - Reset timestamp

When rate limited, response includes:
- Status: 429
- Header: `Retry-After` - Seconds until retry allowed

## Authentication

Most endpoints require authentication. Include the token in the Authorization header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

Public endpoints (no auth required):
- `/health`
- `/ping`
- `/oauth/callback`

## Multi-Tenant Support

For multi-tenant deployments, include the tenant ID:

**Header:**
```
X-Tenant-ID: tenant-123
```

**Or query parameter:**
```
/chat?tenant_id=tenant-123
```
