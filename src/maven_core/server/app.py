"""ASGI application for standalone deployment."""

from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from maven_core.server.middleware import JWTAuthMiddleware, TenantMiddleware

if TYPE_CHECKING:
    from maven_core.agent import Agent


def create_app(agent: "Agent") -> Starlette:
    """Create the ASGI application.

    Args:
        agent: The configured Agent instance

    Returns:
        Starlette application
    """
    from maven_core.auth.jwt_utils import load_key_pair
    from maven_core.server.routes import create_routes

    routes = create_routes(agent)

    # Load JWT key pair for RS256 authentication
    public_key = None
    issuer = None
    if agent.config.auth.builtin and agent.config.auth.builtin.jwt:
        jwt_config = agent.config.auth.builtin.jwt
        key_pair = load_key_pair(
            private_key_path=jwt_config.private_key_path,
            public_key_path=jwt_config.public_key_path,
            key_id=jwt_config.key_id,
        )
        public_key = key_pair.public_key
        issuer = jwt_config.issuer

    # Public paths that don't require authentication
    public_paths = [
        "/health",
        "/ping",
        "/.well-known/jwks.json",
        "/auth/login",
        "/auth/refresh",
    ]

    # Middleware stack (order matters - executed in reverse order)
    # So: CORS -> Auth -> Tenant -> Route handler
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=agent.config.server.cors_origins or ["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
        # JWT Authentication middleware - validates RS256 tokens, adds user to request.state
        Middleware(
            JWTAuthMiddleware,
            public_key=public_key,
            issuer=issuer,
            public_paths=public_paths,
        ),
        # Tenant middleware - requires X-Tenant-ID header or tenant_id query param
        # Validates tenant matches JWT claims
        Middleware(
            TenantMiddleware,
            header_name="X-Tenant-ID",
            query_param="tenant_id",
            enforce_tenant_match=True,
            public_paths=public_paths,
        ),
    ]

    return Starlette(
        routes=routes,
        middleware=middleware,
    )
