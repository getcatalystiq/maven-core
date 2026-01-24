"""HTTP route handlers with Streamable HTTP streaming.

Uses NDJSON (newline-delimited JSON) over chunked HTTP per MCP 2025 spec.
Simple, stateless, no special protocol needed.
"""

import functools
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from maven_core.auth.manager import AuthManager
from maven_core.exceptions import AuthError, InvalidCredentialsError, TokenExpiredError, TokenInvalidError

if TYPE_CHECKING:
    from maven_core.agent import Agent


def require_admin(
    handler: Callable[[Request], Awaitable[Response]],
) -> Callable[[Request], Awaitable[Response]]:
    """Decorator to require admin role for a route handler.

    Checks authentication first (401), then authorization (403).
    """

    @functools.wraps(handler)
    async def wrapper(request: Request) -> Response:
        # Check authentication first (fail closed)
        authenticated_user_id = getattr(request.state, "user_id", None)
        if not authenticated_user_id:
            return JSONResponse({"error": "Authentication required"}, status_code=401)

        # Then check authorization (admin or super_admin)
        roles = getattr(request.state, "roles", [])
        has_admin_access = "admin" in roles or "super_admin" in roles
        if not has_admin_access:
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
        return JSONResponse(
            {
                "status": "ok",
                "timestamp": time.time(),
            }
        )

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

            return JSONResponse(
                {
                    "content": response.content,
                    "session_id": response.session_id,
                    "message_id": response.message_id,
                }
            )
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
                        yield format_ndjson(
                            {
                                "type": "done",
                                "content": full_content,
                                "session_id": session_id or "unknown",
                            }
                        )
                    else:
                        full_content += chunk.content
                        yield format_ndjson(
                            {
                                "type": "chunk",
                                "content": chunk.content,
                            }
                        )
            except Exception as e:
                yield format_ndjson(
                    {
                        "type": "error",
                        "error": str(e),
                    }
                )

        return NDJSONResponse(generate())

    async def skills(request: Request) -> Response:
        """List available skills.

        Query params:
        - user_id: Filter skills by user access
        """
        user_id = request.query_params.get("user_id")

        # TODO: Get user roles from auth and filter skills
        # For now, return empty list until auth is integrated
        return JSONResponse(
            {
                "skills": [],
                "user_id": user_id,
            }
        )

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
        return JSONResponse(
            {
                "sessions": [],
                "user_id": user_id,
                "limit": limit,
                "offset": offset,
            }
        )

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
        return JSONResponse(
            {
                "session_id": session_id,
                "user_id": user_id,
                "turns": [],
            }
        )

    async def connectors(request: Request) -> Response:
        """List configured connectors.

        Query params:
        - user_id: Check connection status for this user
        """
        user_id = request.query_params.get("user_id")

        # TODO: Integrate with ConnectorLoader
        return JSONResponse(
            {
                "connectors": [],
                "user_id": user_id,
            }
        )

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
        return JSONResponse(
            {
                "connector": connector_name,
                "authorization_url": f"https://example.com/oauth?connector={connector_name}",
                "state": "placeholder-state",
            }
        )

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
        return JSONResponse(
            {
                "success": True,
                "message": "OAuth flow completed",
            }
        )

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

        await agent._ensure_initialized()

        if agent.config.auth.mode != "builtin":
            return JSONResponse(
                {"error": "Password login not available in OIDC mode"},
                status_code=400,
            )

        try:
            auth_manager = AuthManager(
                agent.config.auth,
                agent.db,
                agent.config.tenant_id,
                issuer=agent.config.auth.builtin.jwt.issuer if agent.config.auth.builtin and agent.config.auth.builtin.jwt else None,
            )
            tokens = await auth_manager.login(email, password)
            return JSONResponse({
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "expires_in": tokens.expires_in,
            })
        except InvalidCredentialsError:
            return JSONResponse({"error": "Invalid email or password"}, status_code=401)
        except AuthError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

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

        await agent._ensure_initialized()

        if agent.config.auth.mode != "builtin":
            return JSONResponse(
                {"error": "Token refresh not available in OIDC mode"},
                status_code=400,
            )

        try:
            auth_manager = AuthManager(
                agent.config.auth,
                agent.db,
                agent.config.tenant_id,
                issuer=agent.config.auth.builtin.jwt.issuer if agent.config.auth.builtin and agent.config.auth.builtin.jwt else None,
            )
            tokens = await auth_manager.refresh(refresh_token)
            return JSONResponse({
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "expires_in": tokens.expires_in,
            })
        except TokenExpiredError:
            return JSONResponse({"error": "Refresh token expired"}, status_code=401)
        except TokenInvalidError as e:
            return JSONResponse({"error": str(e)}, status_code=401)
        except AuthError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def auth_logout(request: Request) -> Response:
        """Logout and invalidate tokens."""
        # TODO: Integrate with AuthManager.revoke_token
        return JSONResponse({"success": True})

    async def auth_me(request: Request) -> Response:
        """Get current authenticated user info."""
        user = getattr(request.state, "user", None)
        if not user:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        return JSONResponse(
            {
                "user_id": user.get("user_id") or user.get("sub"),
                "email": user.get("email"),
                "roles": user.get("roles", []),
                "tenant_id": user.get("tenant_id"),
            }
        )

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
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)
        limit = int(request.query_params.get("limit", "50"))
        offset = int(request.query_params.get("offset", "0"))

        try:
            # Get total count
            count_result = await agent.db.execute(
                "SELECT COUNT(*) as count FROM users WHERE tenant_id = :tenant_id",
                {"tenant_id": tenant_id},
            )
            total = count_result[0].count if count_result else 0

            # Get users with roles
            users = await agent.db.execute(
                """
                SELECT u.id, u.email, u.email_verified, u.created_at,
                       GROUP_CONCAT(r.name) as roles
                FROM users u
                LEFT JOIN user_roles ur ON u.id = ur.user_id
                LEFT JOIN roles r ON ur.role_id = r.id
                WHERE u.tenant_id = :tenant_id
                GROUP BY u.id
                ORDER BY u.created_at DESC
                LIMIT :limit OFFSET :offset
                """,
                {"tenant_id": tenant_id, "limit": limit, "offset": offset},
            )

            return JSONResponse(
                {
                    "users": [
                        {
                            "user_id": u.id,
                            "email": u.email,
                            "email_verified": bool(u.email_verified),
                            "roles": u.roles.split(",") if u.roles else [],
                            "created_at": u.created_at,
                        }
                        for u in users
                    ],
                    "limit": limit,
                    "offset": offset,
                    "total": total,
                }
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @require_admin
    async def admin_user_create(request: Request) -> Response:
        """Create a new user (admin only)."""
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        email = body.get("email")
        password = body.get("password")
        roles = body.get("roles", ["user"])

        if not email:
            return JSONResponse({"error": "Missing required field: email"}, status_code=400)
        if not password:
            return JSONResponse({"error": "Missing required field: password"}, status_code=400)

        try:
            from maven_core.auth.manager import AuthManager

            auth_manager = AuthManager(agent.config.auth, agent.db, tenant_id)
            user = await auth_manager.register(email, password, roles)

            return JSONResponse(
                {
                    "user_id": user.id,
                    "email": user.email,
                    "roles": user.roles,
                    "created": True,
                },
                status_code=201,
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @require_admin
    async def admin_user_detail(request: Request) -> Response:
        """Get user details (admin only)."""
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = request.path_params["user_id"]

        try:
            users = await agent.db.execute(
                """
                SELECT u.id, u.email, u.email_verified, u.created_at,
                       GROUP_CONCAT(r.name) as roles
                FROM users u
                LEFT JOIN user_roles ur ON u.id = ur.user_id
                LEFT JOIN roles r ON ur.role_id = r.id
                WHERE u.tenant_id = :tenant_id AND u.id = :user_id
                GROUP BY u.id
                """,
                {"tenant_id": tenant_id, "user_id": user_id},
            )

            if not users:
                return JSONResponse({"error": "User not found"}, status_code=404)

            u = users[0]
            return JSONResponse(
                {
                    "user_id": u.id,
                    "email": u.email,
                    "email_verified": bool(u.email_verified),
                    "roles": u.roles.split(",") if u.roles else [],
                    "created_at": u.created_at,
                }
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @require_admin
    async def admin_user_update(request: Request) -> Response:
        """Update user (admin only).

        Body:
        - roles: List of roles to assign
        - email_verified: Boolean
        """
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = request.path_params["user_id"]

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        try:
            # Check user exists
            users = await agent.db.execute(
                "SELECT id FROM users WHERE tenant_id = :tenant_id AND id = :user_id",
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            if not users:
                return JSONResponse({"error": "User not found"}, status_code=404)

            # Update email_verified if provided
            if "email_verified" in body:
                await agent.db.execute(
                    """
                    UPDATE users SET email_verified = :verified, updated_at = CURRENT_TIMESTAMP
                    WHERE tenant_id = :tenant_id AND id = :user_id
                    """,
                    {
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "verified": 1 if body["email_verified"] else 0,
                    },
                )

            # Update roles if provided
            if "roles" in body:
                # Remove existing roles
                await agent.db.execute(
                    "DELETE FROM user_roles WHERE user_id = :user_id",
                    {"user_id": user_id},
                )

                # Add new roles
                for role_name in body["roles"]:
                    role_rows = await agent.db.execute(
                        "SELECT id FROM roles WHERE tenant_id = :tenant_id AND name = :name",
                        {"tenant_id": tenant_id, "name": role_name},
                    )
                    if role_rows:
                        await agent.db.execute(
                            """
                            INSERT INTO user_roles (id, tenant_id, user_id, role_id)
                            VALUES (:id, :tenant_id, :user_id, :role_id)
                            """,
                            {
                                "id": f"ur-{user_id}-{role_name}",
                                "tenant_id": tenant_id,
                                "user_id": user_id,
                                "role_id": role_rows[0].id,
                            },
                        )

            return JSONResponse({"user_id": user_id, "updated": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @require_admin
    async def admin_user_delete(request: Request) -> Response:
        """Delete user (admin only)."""
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = request.path_params["user_id"]

        try:
            # Check user exists
            users = await agent.db.execute(
                "SELECT id FROM users WHERE tenant_id = :tenant_id AND id = :user_id",
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            if not users:
                return JSONResponse({"error": "User not found"}, status_code=404)

            # Delete user roles
            await agent.db.execute(
                "DELETE FROM user_roles WHERE user_id = :user_id",
                {"user_id": user_id},
            )

            # Delete user
            await agent.db.execute(
                "DELETE FROM users WHERE tenant_id = :tenant_id AND id = :user_id",
                {"tenant_id": tenant_id, "user_id": user_id},
            )

            return JSONResponse({"user_id": user_id, "deleted": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @require_admin
    async def admin_roles_list(request: Request) -> Response:
        """List available roles for tenant (admin only).

        GET /admin/roles
        """
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)

        try:
            roles = await agent.db.execute(
                """
                SELECT id, name, description
                FROM roles
                WHERE tenant_id = :tenant_id
                ORDER BY name
                """,
                {"tenant_id": tenant_id},
            )

            return JSONResponse(
                {
                    "roles": [
                        {
                            "id": r.id,
                            "name": r.name,
                            "description": r.description,
                        }
                        for r in roles
                    ],
                    "total": len(roles),
                }
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @require_admin
    async def admin_user_role_assign(request: Request) -> Response:
        """Assign role to user (admin only).

        POST /admin/users/{user_id}/roles
        Body: { role: string }
        """
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = request.path_params["user_id"]

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        role_name = body.get("role")
        if not role_name:
            return JSONResponse({"error": "Missing required field: role"}, status_code=400)

        try:
            # Check user exists
            users = await agent.db.execute(
                "SELECT id FROM users WHERE tenant_id = :tenant_id AND id = :user_id",
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            if not users:
                return JSONResponse({"error": "User not found"}, status_code=404)

            # Find role
            role_rows = await agent.db.execute(
                "SELECT id FROM roles WHERE tenant_id = :tenant_id AND name = :name",
                {"tenant_id": tenant_id, "name": role_name},
            )
            if not role_rows:
                return JSONResponse({"error": f"Role not found: {role_name}"}, status_code=404)

            role_id = role_rows[0].id

            # Check if already assigned
            existing = await agent.db.execute(
                "SELECT id FROM user_roles WHERE user_id = :user_id AND role_id = :role_id",
                {"user_id": user_id, "role_id": role_id},
            )
            if existing:
                return JSONResponse({"error": "Role already assigned"}, status_code=409)

            # Assign role
            await agent.db.execute(
                """
                INSERT INTO user_roles (id, tenant_id, user_id, role_id)
                VALUES (:id, :tenant_id, :user_id, :role_id)
                """,
                {
                    "id": f"ur-{user_id}-{role_name}",
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "role_id": role_id,
                },
            )

            return JSONResponse({"user_id": user_id, "role": role_name, "assigned": True}, status_code=201)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @require_admin
    async def admin_user_role_revoke(request: Request) -> Response:
        """Revoke role from user (admin only).

        DELETE /admin/users/{user_id}/roles/{role_name}
        """
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = request.path_params["user_id"]
        role_name = request.path_params["role_name"]

        try:
            # Check user exists
            users = await agent.db.execute(
                "SELECT id FROM users WHERE tenant_id = :tenant_id AND id = :user_id",
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            if not users:
                return JSONResponse({"error": "User not found"}, status_code=404)

            # Find role
            role_rows = await agent.db.execute(
                "SELECT id FROM roles WHERE tenant_id = :tenant_id AND name = :name",
                {"tenant_id": tenant_id, "name": role_name},
            )
            if not role_rows:
                return JSONResponse({"error": f"Role not found: {role_name}"}, status_code=404)

            role_id = role_rows[0].id

            # Delete role assignment
            await agent.db.execute(
                "DELETE FROM user_roles WHERE user_id = :user_id AND role_id = :role_id",
                {"user_id": user_id, "role_id": role_id},
            )

            return JSONResponse({"user_id": user_id, "role": role_name, "revoked": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @require_admin
    async def admin_user_reset_password(request: Request) -> Response:
        """Reset user password (admin only).

        POST /admin/users/{user_id}/reset-password
        Body: { password: string }
        """
        await agent._ensure_initialized()
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = request.path_params["user_id"]

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        new_password = body.get("password")
        if not new_password:
            return JSONResponse({"error": "Missing required field: password"}, status_code=400)

        if len(new_password) < 8:
            return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)

        try:
            # Check user exists
            users = await agent.db.execute(
                "SELECT id FROM users WHERE tenant_id = :tenant_id AND id = :user_id",
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            if not users:
                return JSONResponse({"error": "User not found"}, status_code=404)

            # Hash new password
            from maven_core.auth.manager import AuthManager
            password_hash = AuthManager.hash_password(new_password)

            # Update password
            await agent.db.execute(
                """
                UPDATE users SET password_hash = :password_hash, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = :tenant_id AND id = :user_id
                """,
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "password_hash": password_hash,
                },
            )

            return JSONResponse({"user_id": user_id, "password_reset": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # Tenant endpoints
    async def tenant_info(request: Request) -> Response:
        """Get current tenant info."""
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return JSONResponse({"error": "No tenant context"}, status_code=400)

        # TODO: Integrate with TenantManager
        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "name": "Placeholder Tenant",
                "settings": {},
            }
        )

    @require_admin
    async def tenant_update(request: Request) -> Response:
        """Update tenant settings (admin only)."""
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return JSONResponse({"error": "No tenant context"}, status_code=400)

        try:
            await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # TODO: Integrate with TenantManager.update
        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "updated": True,
            }
        )

    async def tenant_config(request: Request) -> Response:
        """Get tenant configuration."""
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return JSONResponse({"error": "No tenant context"}, status_code=400)

        # TODO: Integrate with ConfigLoader
        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "config": {},
            }
        )

    @require_admin
    async def tenant_config_update(request: Request) -> Response:
        """Update tenant configuration (admin only)."""
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            return JSONResponse({"error": "No tenant context"}, status_code=400)

        try:
            await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # TODO: Integrate with ConfigLoader.save
        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "config_updated": True,
            }
        )

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
        return JSONResponse(
            {
                "tenants": [t.to_dict() for t in tenants],
                "total": len(tenants),
            }
        )

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
            return JSONResponse(
                {
                    "error": result.message,
                    "tenant_id": result.tenant_id,
                },
                status_code=409,
            )

        return JSONResponse(
            {
                "tenant_id": result.tenant_id,
                "name": result.config.name,
                "status": result.config.status,
                "created_at": result.config.created_at,
                "message": result.message,
            },
            status_code=201,
        )

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

        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "deleted": True,
            }
        )

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

        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "status": "suspended",
            }
        )

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

        return JSONResponse(
            {
                "tenant_id": tenant_id,
                "status": "active",
            }
        )

    @require_admin
    async def admin_tenant_update(request: Request) -> Response:
        """Update tenant settings (admin only).

        PUT /admin/tenants/{tenant_id}
        Body: { name?, settings?, limits?, metadata? }
        """
        from maven_core.provisioning.tenant import TenantManager

        tenant_id = request.path_params["tenant_id"]

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        # Check tenant exists
        existing = await tenant_mgr.get_tenant(tenant_id)
        if not existing:
            return JSONResponse({"error": f"Tenant not found: {tenant_id}"}, status_code=404)

        # Update tenant
        updated = await tenant_mgr.update_tenant(
            tenant_id=tenant_id,
            name=body.get("name"),
            settings=body.get("settings"),
            limits=body.get("limits"),
            metadata=body.get("metadata"),
        )

        if not updated:
            return JSONResponse({"error": "Failed to update tenant"}, status_code=500)

        return JSONResponse(updated.to_dict())

    # Provisioning endpoints
    @require_admin
    async def admin_tiers_list(request: Request) -> Response:
        """List available tenant tiers (admin only).

        GET /admin/tiers
        Returns list of tier configurations with limits and features.
        """
        from maven_core.provisioning.tiers import list_tiers

        tiers = list_tiers()
        return JSONResponse({
            "tiers": [t.to_dict() for t in tiers],
        })

    @require_admin
    async def admin_tenant_provision(request: Request) -> Response:
        """Start tenant provisioning (admin only).

        POST /admin/tenants/provision
        Body: { name, tier?, tenant_id?, settings? }

        Returns job ID immediately (202 Accepted).
        Frontend should redirect to /tenants/provision/{job_id} to stream progress.
        """
        from maven_core.provisioning.tenant import TenantManager

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        name = body.get("name")
        if not name:
            return JSONResponse({"error": "Missing required field: name"}, status_code=400)

        tier = body.get("tier", "starter")
        tenant_id = body.get("tenant_id")
        settings = body.get("settings")

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        # Check if tenant_id already exists (if provided)
        if tenant_id:
            existing = await tenant_mgr.get_tenant(tenant_id)
            if existing:
                return JSONResponse(
                    {"error": f"Tenant already exists: {tenant_id}"},
                    status_code=409,
                )

        # Create provisioning job
        job = await tenant_mgr.create_provisioning_job(
            name=name,
            tier=tier,
            tenant_id=tenant_id,
            settings=settings,
        )

        # Start background provisioning task
        import asyncio

        async def run_provisioning() -> None:
            """Run provisioning in background."""
            async for _ in tenant_mgr.provision_tenant_with_progress(job.id, settings):
                pass  # Just consume the generator to execute steps

        asyncio.create_task(run_provisioning())

        return JSONResponse(
            {
                "job_id": job.id,
                "tenant_id": job.tenant_id,
                "tier": job.tier,
                "status": "pending",
            },
            status_code=202,
        )

    @require_admin
    async def admin_provision_status(request: Request) -> Response:
        """Get provisioning job status (admin only).

        GET /admin/tenants/provision/{job_id}
        Returns current job status (polling fallback).
        """
        from maven_core.provisioning.tenant import TenantManager
        from maven_core.provisioning.tiers import PROVISIONING_STEPS, get_provisioning_steps, get_tier

        job_id = request.path_params["job_id"]

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        job = await tenant_mgr.get_provisioning_job(job_id)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)

        # Get step details for the tier
        tier_config = get_tier(job.tier)
        if tier_config:
            steps = get_provisioning_steps(tier_config)
        else:
            steps = PROVISIONING_STEPS

        # Build step status list
        step_statuses = []
        for i, step in enumerate(steps):
            step_num = i + 1
            if step.id in job.steps_completed:
                status = "completed"
            elif step.id in job.steps_skipped:
                status = "skipped"
            elif step_num == job.current_step and job.status == "running":
                status = "running"
            elif step_num < job.current_step:
                status = "completed"
            else:
                status = "pending"

            step_statuses.append({
                "id": step.id,
                "name": step.name,
                "status": status,
            })

        return JSONResponse({
            **job.to_dict(),
            "steps": step_statuses,
        })

    @require_admin
    async def admin_provision_stream(request: Request) -> Response:
        """Stream provisioning progress (admin only).

        GET /admin/tenants/provision/{job_id}/stream
        Returns NDJSON stream of progress events.

        Event types:
            {"type": "step_started", "step_id": "...", "step_name": "...", "step_number": N}
            {"type": "step_completed", "step_id": "...", "step_number": N}
            {"type": "step_skipped", "step_id": "...", "reason": "..."}
            {"type": "completed", "tenant_id": "..."}
            {"type": "failed", "error": "..."}
        """
        from maven_core.provisioning.tenant import TenantManager

        job_id = request.path_params["job_id"]

        await agent._ensure_initialized()
        tenant_mgr = TenantManager(
            files=agent.files,
            kv=agent.kv,
            db=agent.db,
        )

        # Check job exists
        job = await tenant_mgr.get_provisioning_job(job_id)
        if not job:
            return JSONResponse({"error": "Job not found"}, status_code=404)

        # If job is already completed or failed, return final status
        if job.status in ("completed", "failed"):
            async def generate_final() -> AsyncIterator[str]:
                if job.status == "completed":
                    yield format_ndjson({"type": "completed", "tenant_id": job.tenant_id})
                else:
                    yield format_ndjson({"type": "failed", "error": job.error})

            return NDJSONResponse(generate_final())

        # Stream progress events
        async def generate() -> AsyncIterator[str]:
            async for event in tenant_mgr.provision_tenant_with_progress(job_id):
                yield format_ndjson(event.to_dict())

        return NDJSONResponse(generate())

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
        Route("/admin/users/{user_id}/roles", admin_user_role_assign, methods=["POST"]),
        Route("/admin/users/{user_id}/roles/{role_name}", admin_user_role_revoke, methods=["DELETE"]),
        Route("/admin/users/{user_id}/reset-password", admin_user_reset_password, methods=["POST"]),
        # Admin - Roles
        Route("/admin/roles", admin_roles_list, methods=["GET"]),
        # Admin - Tiers
        Route("/admin/tiers", admin_tiers_list, methods=["GET"]),
        # Admin - Tenants (provisioning routes must come before {tenant_id} routes)
        Route("/admin/tenants", admin_tenants_list, methods=["GET"]),
        Route("/admin/tenants", admin_tenant_create, methods=["POST"]),
        Route("/admin/tenants/provision", admin_tenant_provision, methods=["POST"]),
        Route("/admin/tenants/provision/{job_id}", admin_provision_status, methods=["GET"]),
        Route("/admin/tenants/provision/{job_id}/stream", admin_provision_stream, methods=["GET"]),
        Route("/admin/tenants/{tenant_id}", admin_tenant_detail, methods=["GET"]),
        Route("/admin/tenants/{tenant_id}", admin_tenant_update, methods=["PUT"]),
        Route("/admin/tenants/{tenant_id}", admin_tenant_delete, methods=["DELETE"]),
        Route("/admin/tenants/{tenant_id}/suspend", admin_tenant_suspend, methods=["POST"]),
        Route("/admin/tenants/{tenant_id}/activate", admin_tenant_activate, methods=["POST"]),
        # Tenant (current tenant context)
        Route("/tenant", tenant_info, methods=["GET"]),
        Route("/tenant", tenant_update, methods=["PUT"]),
        Route("/tenant/config", tenant_config, methods=["GET"]),
        Route("/tenant/config", tenant_config_update, methods=["PUT"]),
    ]
