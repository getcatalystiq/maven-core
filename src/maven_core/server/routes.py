"""HTTP route handlers with SSE streaming support."""

import json
import time
from typing import TYPE_CHECKING, AsyncIterator

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from maven_core.agent import Agent


class SSEResponse(StreamingResponse):
    """Server-Sent Events response."""

    media_type = "text/event-stream"

    def __init__(
        self,
        content: AsyncIterator[str],
        status_code: int = 200,
        headers: dict | None = None,
    ) -> None:
        """Initialize SSE response.

        Args:
            content: Async iterator of SSE-formatted strings
            status_code: HTTP status code
            headers: Additional headers
        """
        sse_headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # For nginx
        }
        if headers:
            sse_headers.update(headers)

        super().__init__(
            content=content,
            status_code=status_code,
            headers=sse_headers,
            media_type=self.media_type,
        )


def format_sse(event: str, data: dict | str, event_id: str | None = None) -> str:
    """Format a message for Server-Sent Events.

    Args:
        event: Event type (e.g., "message", "error", "done")
        data: Data to send (dict will be JSON-encoded)
        event_id: Optional event ID

    Returns:
        SSE-formatted string
    """
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    if isinstance(data, dict):
        data = json.dumps(data)
    lines.append(f"data: {data}")
    lines.append("")  # Empty line to end the event
    return "\n".join(lines) + "\n"


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
        """Chat endpoint with SSE streaming.

        Streams response chunks as Server-Sent Events.

        Event types:
        - "content": Content chunk with partial response
        - "done": Final event with complete message info
        - "error": Error occurred during processing
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
            """Generate SSE events from agent stream."""
            try:
                full_content = ""
                async for chunk in agent.stream(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                ):
                    if chunk.done:
                        # Send final event with full content
                        yield format_sse("done", {
                            "content": full_content,
                            "session_id": session_id or "unknown",
                        })
                    else:
                        full_content += chunk.content
                        yield format_sse("content", {
                            "chunk": chunk.content,
                        })
            except Exception as e:
                yield format_sse("error", {
                    "error": str(e),
                })

        return SSEResponse(generate())

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
        """
        user_id = request.query_params.get("user_id")
        if not user_id:
            return JSONResponse(
                {"error": "Missing required query param: user_id"},
                status_code=400,
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
        """
        session_id = request.path_params["session_id"]
        user_id = request.query_params.get("user_id")

        if not user_id:
            return JSONResponse(
                {"error": "Missing required query param: user_id"},
                status_code=400,
            )

        # TODO: Integrate with SessionManager
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

    return [
        # Health
        Route("/health", health, methods=["GET"]),
        Route("/ping", health, methods=["GET"]),  # Alias

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
    ]
