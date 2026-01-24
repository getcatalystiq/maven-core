"""HTTP route handlers with Streamable HTTP streaming.

Uses NDJSON (newline-delimited JSON) over chunked HTTP per MCP 2025 spec.
Simple, stateless, no special protocol needed.
"""

import functools
import json
import time
from typing import TYPE_CHECKING, AsyncIterator, Callable, Awaitable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from maven_core.agent import Agent


def require_admin(handler: Callable[[Request], Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
    """Decorator to require admin role for a route handler.

    Checks authentication first (401), then authorization (403).
    """
    @functools.wraps(handler)
    async def wrapper(request: Request) -> Response:
        # Check authentication first (fail closed)
        authenticated_user_id = getattr(request.state, "user_id", None)
        if not authenticated_user_id:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        # Then check authorization
        roles = getattr(request.state, "roles", [])
        if "admin" not in roles:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        return await handler(request)
    return wrapper


class NDJSONResponse(StreamingResponse):
    """Newline-delimited JSON streaming response (Streamable HTTP).

    Modern streaming format per MCP 2025 spec. Each chunk is a JSON object
    followed by a newline, enabling simple parsing without special protocols.
    """

    media_type = "application/x-ndjson"

    def __init__(
        self,
        content: AsyncIterator[str],
        status_code: int = 200,
        headers: dict | None = None,
    ) -> None:
        ndjson_headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
        if headers:
            ndjson_headers.update(headers)

        super().__init__(
            content=content,
            status_code=status_code,
            headers=ndjson_headers,
            media_type=self.media_type,
        )


def format_ndjson(data: dict) -> str:
    """Format data as NDJSON line.

    Args:
        data: Data to serialize

    Returns:
        JSON string followed by newline
    """
    return json.dumps(data) + "\n"


def create_routes(agent: "Agent") -> list[Route]:
    """Create HTTP routes for the agent.

    Args:
        agent: The configured Agent instance

    Returns:
        List of Starlette routes
    """

    async def health(request: Request) -> Response:
        """Health check endpoint."""
        return JSONResponse({
            "status": "ok",
            "timestamp": time.time(),
        })

    async def chat(request: Request) -> Response:
        """Chat endpoint - handles messages and returns JSON response."""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": "Invalid JSON body"},
                status_code=400,
            )

        message = body.get("message")
        if not message:
            return JSONResponse(
                {"error": "Missing required field: message"},
                status_code=400,
            )

        user_id = body.get("user_id", "anonymous")
        session_id = body.get("session_id")

        try:
            response = await agent.chat(
                message=message,
                user_id=user_id,
                session_id=session_id,
            )

            return JSONResponse({
                "content": response.content,
                "session_id": response.session_id,
                "message_id": response.message_id,
            })
        except Exception as e:
            return JSONResponse(
                {"error": str(e)},
                status_code=500,
            )

    async def chat_stream(request: Request) -> Response:
        """Chat endpoint with streaming response (Streamable HTTP).

        Returns NDJSON stream with chunks:
            {"type": "chunk", "content": "..."}
            {"type": "done", "content": "...", "session_id": "..."}
            {"type": "error", "error": "..."}
        """
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": "Invalid JSON body"},
                status_code=400,
            )

        message = body.get("message")
        if not message:
            return JSONResponse(
                {"error": "Missing required field: message"},
                status_code=400,
            )

        user_id = body.get("user_id", "anonymous")
        session_id = body.get("session_id")

        async def generate() -> AsyncIterator[str]:
            """Generate NDJSON stream."""
            try:
                full_content = ""
                async for chunk in agent.stream(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                ):
                    if chunk.done:
                        yield format_ndjson({
                            "type": "done",
                            "content": full_content,
                            "session_id": session_id or "unknown",
                        })
                    else:
                        full_content += chunk.content
                        yield format_ndjson({
                            "type": "chunk",
                            "content": chunk.content,
                        })
            except Exception as e:
                yield format_ndjson({
                    "type": "error",
                    "error": str(e),
                })

        return NDJSONResponse(generate())

    async def skills(request: Request) -> Response:
        """List available skills.

        Query params:
        - user_id: Filter skills by user access
        """
        user_id = request.query_params.get("user_id")

        # TODO: Get user roles from auth and filter skills
        # For now, return empty list until auth is integrated
        return JSONResponse({
            "skills": [],
            "user_id": user_id,
        })

    async def sessions(request: Request) -> Response:
        """List user sessions.

        Query params:
        - user_id: Required - user to list sessions for
        - limit: Maximum sessions to return (default 50)
        - offset: Number to skip (default 0)

        Authorization:
        - User must be authenticated and can only list their own sessions
        """
        user_id = request.query_params.get("user_id")
        if not user_id:
            return JSONResponse(
                {"error": "Missing required query param: user_id"},
                status_code=400,
            )

        # Authorization check: verify authenticated user matches requested user_id
        # Fail closed: require authentication and matching user
        authenticated_user_id = getattr(request.state, "user_id", None)
        if not authenticated_user_id:
            return JSONResponse(
                {"error": "Authentication required"},
                status_code=401,
            )
        if authenticated_user_id != user_id:
            return JSONResponse(
                {"error": "Not authorized to access sessions for this user"},
                status_code=403,
            )

        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))

        # TODO: Integrate with SessionManager
        # For now, return empty list
        return JSONResponse({
            "sessions": [],
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
        })

    async def session_detail(request: Request) -> Response:
        """Get session details.

        Path params:
        - session_id: Session ID

        Query params:
        - user_id: Required - user ID for authorization

        Authorization:
        - User must be authenticated and own the requested session
        """
        session_id = request.path_params["session_id"]
        user_id = request.query_params.get("user_id")

        if not user_id:
            return JSONResponse(
                {"error": "Missing required query param: user_id"},
                status_code=400,
            )

        # Authorization check: verify authenticated user matches requested user_id
        # Fail closed: require authentication and matching user
        authenticated_user_id = getattr(request.state, "user_id", None)
        if not authenticated_user_id:
            return JSONResponse(
                {"error": "Authentication required"},
                status_code=401,
            )
        if authenticated_user_id != user_id:
            return JSONResponse(
                {"error": "Not authorized to access this session"},
                status_code=403,
            )

        # TODO: Integrate with SessionManager and verify session ownership
        # For now, return empty response
        return JSONResponse({
            "session_id": session_id,
            "user_id": user_id,
            "turns": [],
        })

    async def connectors(request: Request) -> Response:
        """List configured connectors.

        Query params:
        - user_id: Check connection status for this user
        """
        user_id = request.query_params.get("user_id")

        # TODO: Integrate with ConnectorLoader
        return JSONResponse({
            "connectors": [],
            "user_id": user_id,
        })

    async def oauth_start(request: Request) -> Response:
        """Start OAuth flow for a connector.

        Path params:
        - connector_name: Connector to authenticate

        Body:
        - user_id: User initiating the flow
        - redirect_uri: OAuth callback URL
        """
        connector_name = request.path_params["connector_name"]

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": "Invalid JSON body"},
                status_code=400,
            )

        user_id = body.get("user_id")
        redirect_uri = body.get("redirect_uri")

        if not user_id or not redirect_uri:
            return JSONResponse(
                {"error": "Missing required fields: user_id, redirect_uri"},
                status_code=400,
            )

        # TODO: Integrate with ConnectorLoader.start_oauth_flow
        return JSONResponse({
            "connector": connector_name,
            "authorization_url": f"https://example.com/oauth?connector={connector_name}",
            "state": "placeholder-state",
        })

    async def oauth_callback(request: Request) -> Response:
        """OAuth callback handler.

        Query params:
        - code: Authorization code
        - state: OAuth state for verification
        """
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code or not state:
            return JSONResponse(
                {"error": "Missing required params: code, state"},
                status_code=400,
            )

        # TODO: Integrate with ConnectorLoader.complete_oauth_flow
        return JSONResponse({
            "success": True,
            "message": "OAuth flow completed",
        })

    # Auth endpoints
    async def auth_login(request: Request) -> Response:
        """Login endpoint.

        Body:
        - email: User email
        - password: User password

        Returns JWT tokens on success.
        """
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        email = body.get("email")
        password = body.get("password")

        if not email or not password:
            return JSONResponse(
                {"error": "Missing required fields: email, password"},
                status_code=400,
            )

        # TODO: Integrate with AuthManager.authenticate
        return JSONResponse(
            {"error": "Authentication not implemented. Configure an auth provider."},
            status_code=501,
        )

    async def auth_refresh(request: Request) -> Response:
        """Refresh access token.

        Body:
        - refresh_token: Valid refresh token
        """
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        refresh_token = body.get("refresh_token")
        if not refresh_token:
            return JSONResponse(
                {"error": "Missing required field: refresh_token"},
                status_code=400,
            )

        # TODO: Integrate with AuthManager.refresh_token
        return JSONResponse(
            {"error": "Token refresh not implemented. Configure an auth provider."},
            status_code=501,
        )

    async def auth_logout(request: Request) -> Response:
        """Logout and invalidate tokens."""
        # TODO: Integrate with AuthManager.revoke_token
        return JSONResponse({"success": True})

    async def auth_me(request: Request) -> Response:
        """Get current authenticated user info."""
        user = getattr(request.state, "user", None)
        if not user:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        return JSONResponse({
            "user_id": user.get("user_id") or user.get("sub"),
            "email": user.get("email"),
            "roles": user.get("roles", []),
            "tenant_id": user.get("tenant_id"),
        })

    async def jwks(request: Request) -> Response:
        """JWKS endpoint for JWT verification.

        Returns the public keys for verifying JWT tokens signed by this server.
        This enables clients to verify tokens without sharing secrets.
        """
        from maven_core.auth.jwt_utils import create_jwks, load_key_pair

        if not agent.config.auth.builtin or not agent.config.auth.builtin.jwt:
            return JSONResponse(
                {"error": "JWT authentication not configured"},
                status_code=501,
            )

        try:
            jwt_config = agent.config.auth.builtin.jwt
            key_pair = load_key_pair(
                private_key_path=jwt_config.private_key_path,
                public_key_path=jwt_config.public_key_path,
                key_id=jwt_config.key_id,
            )
            jwks_data = create_jwks(key_pair)
            return JSONResponse(jwks_data)
        except Exception as e:
            return JSONResponse(
                {"error": str(e)},
                status_code=500,
            )

    # Admin endpoints
    @require_admin
    async def admin_users_list(request: Request) -> Response:
        """List users (admin only).

        Query params:
        - limit: Max users to return (default 50)
        - offset: Number to skip (default 0)
        """
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))

        # TODO: Integrate with UserManager
        return JSONResponse({
            "users": [],
            "limit": limit,
            "offset": offset,
            "total": 0,
        })

    @require_admin
    async def admin_user_create(request: Request) -> Response:
        """Create a new user (admin only)."""
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        email = body.get("email")
        if not email:
            return JSONResponse({"error": "Missing required field: email"}, status_code=400)

        # TODO: Integrate with UserManager.create_user
        return JSONResponse({
            "user_id": "placeholder-user-id",
            "email": email,
            "created": True,
        }, status_code=201)

    @require_admin
    async def admin_user_detail(request: Request) -> Response:
        """Get user details (admin only)."""
        user_id = request.path_params["user_id"]

        # TODO: Integrate with UserManager.get_user
        return JSONResponse({
            "user_id": user_id,
            "email": "placeholder@example.com",
            "roles": [],
            "created_at": time.time(),
        })

    @require_admin
    async def admin_user_update(request: Request) -> Response:
        """Update user (admin only)."""
        user_id = request.path_params["user_id"]

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # TODO: Integrate with UserManager.update_user
        return JSONResponse({
            "user_id": user_id,
            "updated": True,
        })

    @require_admin
    async def admin_user_delete(request: Request) -> Response:
        """Delete user (admin only)."""
        user_id = request.path_params["user_id"]

        # TODO: Integrate with UserManager.delete_user
        return JSONResponse({
            "user_id": user_id,
            "deleted": True,
        })

    # Tenant endpoints
    async def tenant_info(request: Request) -> Response:
        """Get current tenant info."""
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return JSONResponse({"error": "No tenant context"}, status_code=400)

        # TODO: Integrate with TenantManager
        return JSONResponse({
            "tenant_id": tenant_id,
            "name": "Placeholder Tenant",
            "settings": {},
        })

    @require_admin
    async def tenant_update(request: Request) -> Response:
        """Update tenant settings (admin only)."""
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return JSONResponse({"error": "No tenant context"}, status_code=400)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # TODO: Integrate with TenantManager.update
        return JSONResponse({
            "tenant_id": tenant_id,
            "updated": True,
        })

    async def tenant_config(request: Request) -> Response:
        """Get tenant configuration."""
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return JSONResponse({"error": "No tenant context"}, status_code=400)

        # TODO: Integrate with ConfigLoader
        return JSONResponse({
            "tenant_id": tenant_id,
            "config": {},
        })

    @require_admin
    async def tenant_config_update(request: Request) -> Response:
        """Update tenant configuration (admin only)."""
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return JSONResponse({"error": "No tenant context"}, status_code=400)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # TODO: Integrate with ConfigLoader.save
        return JSONResponse({
            "tenant_id": tenant_id,
            "config_updated": True,
        })

    # Admin - Tenant management
    @require_admin
    async def admin_tenants_list(request: Request) -> Response:
        """List all tenants (admin only)."""
        from maven_core.provisioning.tenant import TenantManager

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        tenants = await tenant_mgr.list_tenants()
        return JSONResponse({
            "tenants": [t.to_dict() for t in tenants],
            "total": len(tenants),
        })

    @require_admin
    async def admin_tenant_create(request: Request) -> Response:
        """Create a new tenant (admin only).

        Request body:
            - name: Tenant display name (required)
            - tenant_id: Custom tenant ID (optional, auto-generated if not provided)
            - settings: Initial settings (optional)
            - limits: Resource limits (optional)
            - metadata: Additional metadata (optional)
        """
        from maven_core.provisioning.tenant import TenantManager

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        name = body.get("name")
        if not name:
            return JSONResponse({"error": "Missing required field: name"}, status_code=400)

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        result = await tenant_mgr.create_tenant(
            name=name,
            tenant_id=body.get("tenant_id"),
            settings=body.get("settings"),
            limits=body.get("limits"),
            metadata=body.get("metadata"),
        )

        if not result.success:
            return JSONResponse({
                "error": result.message,
                "tenant_id": result.tenant_id,
            }, status_code=409)

        return JSONResponse({
            "tenant_id": result.tenant_id,
            "name": result.config.name,
            "status": result.config.status,
            "created_at": result.config.created_at,
            "message": result.message,
        }, status_code=201)

    @require_admin
    async def admin_tenant_detail(request: Request) -> Response:
        """Get tenant details (admin only)."""
        from maven_core.provisioning.tenant import TenantManager

        tenant_id = request.path_params["tenant_id"]

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        tenant = await tenant_mgr.get_tenant(tenant_id)
        if not tenant:
            return JSONResponse({"error": f"Tenant not found: {tenant_id}"}, status_code=404)

        return JSONResponse(tenant.to_dict())

    @require_admin
    async def admin_tenant_delete(request: Request) -> Response:
        """Delete a tenant (admin only)."""
        from maven_core.provisioning.tenant import TenantManager

        tenant_id = request.path_params["tenant_id"]

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        success = await tenant_mgr.delete_tenant(tenant_id)
        if not success:
            return JSONResponse({"error": f"Tenant not found: {tenant_id}"}, status_code=404)

        return JSONResponse({
            "tenant_id": tenant_id,
            "deleted": True,
        })

    @require_admin
    async def admin_tenant_suspend(request: Request) -> Response:
        """Suspend a tenant (admin only)."""
        from maven_core.provisioning.tenant import TenantManager

        tenant_id = request.path_params["tenant_id"]

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        success = await tenant_mgr.suspend_tenant(tenant_id)
        if not success:
            return JSONResponse({"error": f"Tenant not found: {tenant_id}"}, status_code=404)

        return JSONResponse({
            "tenant_id": tenant_id,
            "status": "suspended",
        })

    @require_admin
    async def admin_tenant_activate(request: Request) -> Response:
        """Activate a suspended tenant (admin only)."""
        from maven_core.provisioning.tenant import TenantManager

        tenant_id = request.path_params["tenant_id"]

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        success = await tenant_mgr.activate_tenant(tenant_id)
        if not success:
            return JSONResponse({"error": f"Tenant not found: {tenant_id}"}, status_code=404)

        return JSONResponse({
            "tenant_id": tenant_id,
            "status": "active",
        })

    return [
        # Health
        Route("/health", health, methods=["GET"]),
        Route("/ping", health, methods=["GET"]),  # Alias

        # Auth
        Route("/auth/login", auth_login, methods=["POST"]),
        Route("/auth/refresh", auth_refresh, methods=["POST"]),
        Route("/auth/logout", auth_logout, methods=["POST"]),
        Route("/auth/me", auth_me, methods=["GET"]),
        Route("/.well-known/jwks.json", jwks, methods=["GET"]),

        # Chat
        Route("/chat", chat, methods=["POST"]),
        Route("/chat/stream", chat_stream, methods=["POST"]),
        Route("/invocations", chat_stream, methods=["POST"]),  # AWS compatibility

        # Skills
        Route("/skills", skills, methods=["GET"]),

        # Sessions
        Route("/sessions", sessions, methods=["GET"]),
        Route("/sessions/{session_id}", session_detail, methods=["GET"]),

        # Connectors
        Route("/connectors", connectors, methods=["GET"]),
        Route("/connectors/{connector_name}/oauth/start", oauth_start, methods=["POST"]),
        Route("/oauth/callback", oauth_callback, methods=["GET"]),

        # Admin - Users
        Route("/admin/users", admin_users_list, methods=["GET"]),
        Route("/admin/users", admin_user_create, methods=["POST"]),
        Route("/admin/users/{user_id}", admin_user_detail, methods=["GET"]),
        Route("/admin/users/{user_id}", admin_user_update, methods=["PUT"]),
        Route("/admin/users/{user_id}", admin_user_delete, methods=["DELETE"]),

        # Admin - Tenants
        Route("/admin/tenants", admin_tenants_list, methods=["GET"]),
        Route("/admin/tenants", admin_tenant_create, methods=["POST"]),
        Route("/admin/tenants/{tenant_id}", admin_tenant_detail, methods=["GET"]),
        Route("/admin/tenants/{tenant_id}", admin_tenant_delete, methods=["DELETE"]),
        Route("/admin/tenants/{tenant_id}/suspend", admin_tenant_suspend, methods=["POST"]),
        Route("/admin/tenants/{tenant_id}/activate", admin_tenant_activate, methods=["POST"]),

        # Tenant (current tenant context)
        Route("/tenant", tenant_info, methods=["GET"]),
        Route("/tenant", tenant_update, methods=["PUT"]),
        Route("/tenant/config", tenant_config, methods=["GET"]),
        Route("/tenant/config", tenant_config_update, methods=["PUT"]),
    ]
