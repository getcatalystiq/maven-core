"""Authentication middleware for the HTTP server."""

import json
from typing import Callable, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from maven_core.auth.manager import AuthManager


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware for JWT/OIDC authentication.

    Validates authentication tokens and adds user info to request state.

    Unauthenticated paths can be configured (e.g., /health, /ping).
    """

    def __init__(
        self,
        app: Any,
        auth_manager: AuthManager,
        public_paths: list[str] | None = None,
    ) -> None:
        """Initialize authentication middleware.

        Args:
            app: The ASGI application
            auth_manager: Authentication manager
            public_paths: Paths that don't require authentication
        """
        super().__init__(app)
        self.auth_manager = auth_manager
        self.public_paths = set(public_paths or ["/health", "/ping", "/oauth/callback"])

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        """Process the request and validate authentication.

        Args:
            request: The incoming request
            call_next: Next middleware/handler in chain

        Returns:
            Response from handler or 401 error
        """
        # Skip authentication for public paths
        if request.url.path in self.public_paths:
            return await call_next(request)

        # Get token from Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "Missing or invalid Authorization header"},
                status_code=401,
            )

        token = auth_header[7:]  # Remove "Bearer " prefix

        try:
            # Validate token
            user = await self.auth_manager.validate_token(token)
            if not user:
                return JSONResponse(
                    {"error": "Invalid or expired token"},
                    status_code=401,
                )

            # Add user to request state
            request.state.user = user
            request.state.user_id = user.get("user_id") or user.get("sub")
            request.state.roles = user.get("roles", [])

        except Exception as e:
            return JSONResponse(
                {"error": f"Authentication failed: {str(e)}"},
                status_code=401,
            )

        return await call_next(request)


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware for multi-tenant isolation.

    Extracts tenant ID from request and validates access.
    Ensures the authenticated user belongs to the requested tenant.
    """

    def __init__(
        self,
        app: Any,
        header_name: str = "X-Tenant-ID",
        query_param: str = "tenant_id",
        enforce_tenant_match: bool = True,
    ) -> None:
        """Initialize tenant middleware.

        Args:
            app: The ASGI application
            header_name: Header to extract tenant ID from
            query_param: Query param to extract tenant ID from
            enforce_tenant_match: Whether to enforce tenant ID matches user's tenant
        """
        super().__init__(app)
        self.header_name = header_name
        self.query_param = query_param
        self.enforce_tenant_match = enforce_tenant_match

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        """Process the request and extract/validate tenant ID.

        Validates that the requested tenant ID matches the authenticated
        user's tenant from their JWT claims.

        Args:
            request: The incoming request
            call_next: Next middleware/handler in chain

        Returns:
            Response from handler, 400 for missing tenant, or 403 for mismatch
        """
        # Try to get tenant ID from header, then query param
        tenant_id = request.headers.get(self.header_name)
        if not tenant_id:
            tenant_id = request.query_params.get(self.query_param)

        if not tenant_id:
            return JSONResponse(
                {"error": f"Missing required header {self.header_name} or query param {self.query_param}"},
                status_code=400,
            )

        # Validate tenant ID matches authenticated user's tenant
        if self.enforce_tenant_match:
            user = getattr(request.state, "user", None)
            if user:
                user_tenant_id = user.get("tenant_id")
                if user_tenant_id and user_tenant_id != tenant_id:
                    return JSONResponse(
                        {"error": "Not authorized to access this tenant"},
                        status_code=403,
                    )

        # Add tenant to request state
        request.state.tenant_id = tenant_id

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiting middleware.

    For production, use a distributed rate limiter (Redis-based).
    """

    def __init__(
        self,
        app: Any,
        requests_per_minute: int = 60,
    ) -> None:
        """Initialize rate limit middleware.

        Args:
            app: The ASGI application
            requests_per_minute: Maximum requests per minute per IP
        """
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self._request_counts: dict[str, list[float]] = {}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        """Process the request and check rate limit.

        Args:
            request: The incoming request
            call_next: Next middleware/handler in chain

        Returns:
            Response from handler or 429 error
        """
        import time

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"

        # Clean old requests (older than 1 minute)
        now = time.time()
        if client_ip in self._request_counts:
            self._request_counts[client_ip] = [
                t for t in self._request_counts[client_ip]
                if now - t < 60
            ]
        else:
            self._request_counts[client_ip] = []

        # Check rate limit
        if len(self._request_counts[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                {"error": "Rate limit exceeded. Try again later."},
                status_code=429,
                headers={"Retry-After": "60"},
            )

        # Record this request
        self._request_counts[client_ip].append(now)

        return await call_next(request)
