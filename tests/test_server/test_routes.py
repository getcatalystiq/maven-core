"""Tests for server routes."""

import pytest
from starlette.testclient import TestClient

from maven_core.agent import Agent
from maven_core.server.app import create_app
from maven_core.server.routes import format_ndjson, NDJSONResponse


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
        "llm": {"provider": "mock", "model": "mock"},
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

    def test_stream_returns_ndjson_by_default(self, client: TestClient) -> None:
        """Stream returns NDJSON content type by default (Streamable HTTP)."""
        response = client.post(
            "/chat/stream",
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers["content-type"]

    def test_stream_contains_ndjson_chunks(self, client: TestClient) -> None:
        """Stream contains NDJSON chunks."""
        response = client.post(
            "/chat/stream",
            json={"message": "Hello"},
        )

        content = response.text
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) >= 1

        # Parse each line as JSON
        import json
        for line in lines:
            data = json.loads(line)
            assert "type" in data
            assert data["type"] in ("chunk", "done", "error")

    def test_invocations_alias(self, client: TestClient) -> None:
        """Invocations endpoint is an alias for stream."""
        response = client.post(
            "/invocations",
            json={"message": "Hello"},
        )

        assert response.status_code == 200
        # Default is now NDJSON
        assert "application/x-ndjson" in response.headers["content-type"]

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

    def test_sessions_requires_authentication(self, client: TestClient) -> None:
        """Sessions requires authentication."""
        response = client.get("/sessions?user_id=user-123")

        # Fail closed: unauthenticated requests return 401
        assert response.status_code == 401
        assert "authentication" in response.json()["error"].lower()


class TestSessionDetailEndpoint:
    """Tests for session detail endpoint."""

    def test_session_detail_requires_user_id(self, client: TestClient) -> None:
        """Session detail requires user_id."""
        response = client.get("/sessions/session-123")

        assert response.status_code == 400

    def test_session_detail_requires_authentication(self, client: TestClient) -> None:
        """Session detail requires authentication."""
        response = client.get("/sessions/session-123?user_id=user-123")

        # Fail closed: unauthenticated requests return 401
        assert response.status_code == 401
        assert "authentication" in response.json()["error"].lower()


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


class TestFormatNDJSON:
    """Tests for NDJSON formatting (Streamable HTTP)."""

    def test_format_ndjson_basic(self) -> None:
        """Format NDJSON with basic data."""
        import json
        result = format_ndjson({"type": "chunk", "content": "Hello"})

        assert result.endswith("\n")
        parsed = json.loads(result)
        assert parsed["type"] == "chunk"
        assert parsed["content"] == "Hello"

    def test_format_ndjson_complex(self) -> None:
        """Format NDJSON with complex nested data."""
        import json
        data = {
            "type": "done",
            "content": "Full response",
            "metadata": {"session_id": "123", "tokens": 42},
        }
        result = format_ndjson(data)

        parsed = json.loads(result)
        assert parsed == data

    def test_format_ndjson_is_single_line(self) -> None:
        """NDJSON output is a single line."""
        result = format_ndjson({"key": "value"})

        # Should be exactly one line (content + newline)
        lines = result.split("\n")
        assert len(lines) == 2  # content + empty string after final newline
        assert lines[1] == ""
