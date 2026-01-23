"""ASGI application for standalone deployment."""

from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

if TYPE_CHECKING:
    from maven_core.agent import Agent


def create_app(agent: "Agent") -> Starlette:
    """Create the ASGI application.

    Args:
        agent: The configured Agent instance

    Returns:
        Starlette application
    """
    from maven_core.server.routes import create_routes

    routes = create_routes(agent)

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=agent.config.server.cors_origins or ["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ]

    return Starlette(
        routes=routes,
        middleware=middleware,
    )
