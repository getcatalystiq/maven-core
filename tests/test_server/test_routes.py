"""Tests for server routes."""

import pytest
from starlette.testclient import TestClient

from maven_core.agent import Agent
from maven_core.server.app import create_app
from maven_core.server.routes import format_sse, SSEResponse


@pytest.fixture
def agent(tmp_path) -> Agent:
    """Create a test agent."""
    config = {
        "storage": {
            "files": {"backend": "local", "path": str(tmp_path / "files")},
            "kv": {"backend": "memory"},
            "database": {"backend": "sqlite", "path": str(tmp_path / "db.sqlite")},
        },
        "provisioning": {"backend": "local"},
    }
    return Agent.from_dict(config)


@pytest.fixture
def client(agent: Agent) -> TestClient:
    """Create a test client."""
    app = create_app(agent)
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        """Health endpoint returns status ok."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_ping_alias(self, client: TestClient) -> None:
        """Ping endpoint is an alias for health."""
        response = client.get("/ping")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestChatEndpoint:
    """Tests for chat endpoint."""

    def test_chat_returns_response(self, client: TestClient) -> None:
        """Chat returns a response."""
        response = client.post(
            "/chat",
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert "session_id" in data
        assert "message_id" in data

    def test_chat_with_user_id(self, client: TestClient) -> None:
        """Chat accepts user_id."""
        response = client.post(
            "/chat",
            json={"message": "Hello", "user_id": "user-123"},
        )

        assert response.status_code == 200

    def test_chat_with_session_id(self, client: TestClient) -> None:
        """Chat accepts session_id."""
        response = client.post(
            "/chat",
            json={"message": "Hello", "session_id": "session-abc"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-abc"

    def test_chat_missing_message(self, client: TestClient) -> None:
        """Chat returns 400 when message is missing."""
        response = client.post(
            "/chat",
            json={},
        )

        assert response.status_code == 400
        assert "message" in response.json()["error"].lower()

    def test_chat_invalid_json(self, client: TestClient) -> None:
        """Chat returns 400 for invalid JSON."""
        response = client.post(
            "/chat",
            content="not json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400


class TestStreamEndpoint:
    """Tests for streaming chat endpoint."""

    def test_stream_returns_sse(self, client: TestClient) -> None:
        """Stream returns SSE content type."""
        response = client.post(
            "/chat/stream",
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    def test_stream_contains_events(self, client: TestClient) -> None:
        """Stream contains SSE events."""
        response = client.post(
            "/chat/stream",
            json={"message": "Hello"},
        )

        content = response.text
        assert "event: content" in content
        assert "event: done" in content
        assert "data:" in content

    def test_invocations_alias(self, client: TestClient) -> None:
        """Invocations endpoint is an alias for stream."""
        response = client.post(
            "/invocations",
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    def test_stream_missing_message(self, client: TestClient) -> None:
        """Stream returns 400 when message is missing."""
        response = client.post(
            "/chat/stream",
            json={},
        )

        assert response.status_code == 400


class TestSkillsEndpoint:
    """Tests for skills endpoint."""

    def test_skills_returns_list(self, client: TestClient) -> None:
        """Skills endpoint returns a list."""
        response = client.get("/skills")

        assert response.status_code == 200
        data = response.json()
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_skills_with_user_id(self, client: TestClient) -> None:
        """Skills accepts user_id query param."""
        response = client.get("/skills?user_id=user-123")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user-123"


class TestSessionsEndpoint:
    """Tests for sessions endpoint."""

    def test_sessions_requires_user_id(self, client: TestClient) -> None:
        """Sessions requires user_id."""
        response = client.get("/sessions")

        assert response.status_code == 400
        assert "user_id" in response.json()["error"].lower()

    def test_sessions_returns_list(self, client: TestClient) -> None:
        """Sessions returns a list."""
        response = client.get("/sessions?user_id=user-123")

        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_sessions_pagination(self, client: TestClient) -> None:
        """Sessions accepts pagination params."""
        response = client.get("/sessions?user_id=user-123&limit=10&offset=5")

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 5


class TestSessionDetailEndpoint:
    """Tests for session detail endpoint."""

    def test_session_detail_requires_user_id(self, client: TestClient) -> None:
        """Session detail requires user_id."""
        response = client.get("/sessions/session-123")

        assert response.status_code == 400

    def test_session_detail_returns_session(self, client: TestClient) -> None:
        """Session detail returns session info."""
        response = client.get("/sessions/session-123?user_id=user-123")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-123"
        assert data["user_id"] == "user-123"


class TestConnectorsEndpoint:
    """Tests for connectors endpoint."""

    def test_connectors_returns_list(self, client: TestClient) -> None:
        """Connectors returns a list."""
        response = client.get("/connectors")

        assert response.status_code == 200
        data = response.json()
        assert "connectors" in data


class TestOAuthEndpoints:
    """Tests for OAuth endpoints."""

    def test_oauth_start_requires_body(self, client: TestClient) -> None:
        """OAuth start requires body."""
        response = client.post(
            "/connectors/slack/oauth/start",
            json={},
        )

        assert response.status_code == 400

    def test_oauth_start_returns_url(self, client: TestClient) -> None:
        """OAuth start returns authorization URL."""
        response = client.post(
            "/connectors/slack/oauth/start",
            json={"user_id": "user-123", "redirect_uri": "https://app.example.com/callback"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "authorization_url" in data
        assert "state" in data

    def test_oauth_callback_requires_params(self, client: TestClient) -> None:
        """OAuth callback requires code and state."""
        response = client.get("/oauth/callback")

        assert response.status_code == 400

    def test_oauth_callback_success(self, client: TestClient) -> None:
        """OAuth callback completes successfully."""
        response = client.get("/oauth/callback?code=test-code&state=test-state")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestFormatSSE:
    """Tests for SSE formatting."""

    def test_format_sse_basic(self) -> None:
        """Format SSE with basic data."""
        result = format_sse("message", {"text": "Hello"})

        assert "event: message" in result
        assert 'data: {"text": "Hello"}' in result
        assert result.endswith("\n\n")

    def test_format_sse_with_id(self) -> None:
        """Format SSE with event ID."""
        result = format_sse("message", "data", event_id="123")

        assert "id: 123" in result
        assert "event: message" in result
        assert "data: data" in result

    def test_format_sse_string_data(self) -> None:
        """Format SSE with string data."""
        result = format_sse("ping", "pong")

        assert "data: pong" in result
