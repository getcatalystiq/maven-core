"""HTTP route handlers."""

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from maven_core.agent import Agent


def create_routes(agent: "Agent") -> list[Route]:
    """Create HTTP routes for the agent.

    Args:
        agent: The configured Agent instance

    Returns:
        List of Starlette routes
    """

    async def health(request: Request) -> Response:
        """Health check endpoint."""
        return JSONResponse({"status": "ok"})

    async def chat(request: Request) -> Response:
        """Chat endpoint - handles messages and streams responses."""
        body = await request.json()
        message = body.get("message", "")
        user_id = body.get("user_id", "anonymous")
        session_id = body.get("session_id")

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

    async def skills(request: Request) -> Response:
        """List available skills."""
        # TODO: Implement skills listing with role filtering
        return JSONResponse({"skills": []})

    async def sessions(request: Request) -> Response:
        """List user sessions."""
        # TODO: Implement sessions listing
        return JSONResponse({"sessions": []})

    return [
        Route("/health", health, methods=["GET"]),
        Route("/chat", chat, methods=["POST"]),
        Route("/skills", skills, methods=["GET"]),
        Route("/sessions", sessions, methods=["GET"]),
    ]
