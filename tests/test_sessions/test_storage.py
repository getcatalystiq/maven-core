"""Tests for session storage."""

import pytest
import time

from maven_core.backends.files.local import LocalFileStore
from maven_core.backends.kv.memory import MemoryKVStore
from maven_core.sessions.storage import (
    Session,
    SessionMetadata,
    SessionStorage,
    Turn,
)


@pytest.fixture
def file_store(tmp_path) -> LocalFileStore:
    """Create a local file store for testing."""
    return LocalFileStore(tmp_path)


@pytest.fixture
def kv_store() -> MemoryKVStore:
    """Create a memory KV store for testing."""
    return MemoryKVStore()


@pytest.fixture
def storage(file_store, kv_store) -> SessionStorage:
    """Create session storage for testing."""
    return SessionStorage(file_store, kv_store, "test-tenant")


class TestTurn:
    """Tests for Turn dataclass."""

    def test_turn_to_dict(self) -> None:
        """Convert turn to dictionary."""
        turn = Turn(
            id="turn-123",
            role="user",
            content="Hello",
            timestamp=1234567890.0,
            metadata={"key": "value"},
        )

        d = turn.to_dict()

        assert d["id"] == "turn-123"
        assert d["role"] == "user"
        assert d["content"] == "Hello"
        assert d["timestamp"] == 1234567890.0
        assert d["metadata"] == {"key": "value"}

    def test_turn_from_dict(self) -> None:
        """Create turn from dictionary."""
        d = {
            "id": "turn-456",
            "role": "assistant",
            "content": "Hi there!",
            "timestamp": 1234567890.0,
            "metadata": {"tokens": 10},
        }

        turn = Turn.from_dict(d)

        assert turn.id == "turn-456"
        assert turn.role == "assistant"
        assert turn.content == "Hi there!"
        assert turn.metadata == {"tokens": 10}


class TestSessionMetadata:
    """Tests for SessionMetadata dataclass."""

    def test_metadata_to_dict(self) -> None:
        """Convert metadata to dictionary."""
        meta = SessionMetadata(
            session_id="session-abc",
            tenant_id="tenant-1",
            user_id="user-1",
            created_at=1234567890.0,
            updated_at=1234567900.0,
            turn_count=5,
            title="Test Session",
        )

        d = meta.to_dict()

        assert d["session_id"] == "session-abc"
        assert d["tenant_id"] == "tenant-1"
        assert d["user_id"] == "user-1"
        assert d["turn_count"] == 5
        assert d["title"] == "Test Session"

    def test_metadata_from_dict(self) -> None:
        """Create metadata from dictionary."""
        d = {
            "session_id": "session-xyz",
            "tenant_id": "tenant-2",
            "user_id": "user-2",
            "created_at": 1234567890.0,
            "updated_at": 1234567890.0,
            "turn_count": 0,
            "title": None,
        }

        meta = SessionMetadata.from_dict(d)

        assert meta.session_id == "session-xyz"
        assert meta.user_id == "user-2"
        assert meta.title is None


class TestSessionStorage:
    """Tests for SessionStorage."""

    @pytest.mark.asyncio
    async def test_create_session(self, storage: SessionStorage) -> None:
        """Create a new session."""
        meta = await storage.create_session("user-1")

        assert meta.session_id.startswith("session-")
        assert meta.tenant_id == "test-tenant"
        assert meta.user_id == "user-1"
        assert meta.turn_count == 0
        assert meta.title is None

    @pytest.mark.asyncio
    async def test_create_session_with_id(self, storage: SessionStorage) -> None:
        """Create session with specific ID."""
        meta = await storage.create_session("user-1", session_id="my-session")

        assert meta.session_id == "my-session"

    @pytest.mark.asyncio
    async def test_create_session_with_title(self, storage: SessionStorage) -> None:
        """Create session with title."""
        meta = await storage.create_session(
            "user-1",
            session_id="titled-session",
            title="My Conversation",
        )

        assert meta.title == "My Conversation"

    @pytest.mark.asyncio
    async def test_get_session(self, storage: SessionStorage) -> None:
        """Get a session with all turns."""
        # Create session
        meta = await storage.create_session("user-1", session_id="get-test")

        # Add turns
        await storage.append_turn("user-1", "get-test", "user", "Hello")
        await storage.append_turn("user-1", "get-test", "assistant", "Hi there!")

        # Get session
        session = await storage.get_session("user-1", "get-test")

        assert session is not None
        assert session.metadata.session_id == "get-test"
        assert len(session.turns) == 2
        assert session.turns[0].role == "user"
        assert session.turns[0].content == "Hello"
        assert session.turns[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, storage: SessionStorage) -> None:
        """Get non-existent session returns None."""
        session = await storage.get_session("user-1", "nonexistent")
        assert session is None

    @pytest.mark.asyncio
    async def test_get_session_wrong_user(self, storage: SessionStorage) -> None:
        """Cannot get another user's session."""
        await storage.create_session("user-1", session_id="user1-session")

        # Try to get as different user
        session = await storage.get_session("user-2", "user1-session")
        assert session is None

    @pytest.mark.asyncio
    async def test_get_metadata(self, storage: SessionStorage) -> None:
        """Get session metadata only."""
        await storage.create_session("user-1", session_id="meta-test", title="Test")

        meta = await storage.get_metadata("meta-test")

        assert meta is not None
        assert meta.session_id == "meta-test"
        assert meta.title == "Test"

    @pytest.mark.asyncio
    async def test_append_turn(self, storage: SessionStorage) -> None:
        """Append a turn to a session."""
        await storage.create_session("user-1", session_id="turn-test")

        turn = await storage.append_turn(
            "user-1",
            "turn-test",
            "user",
            "What is 2+2?",
            metadata={"source": "test"},
        )

        assert turn.id.startswith("turn-")
        assert turn.role == "user"
        assert turn.content == "What is 2+2?"
        assert turn.metadata == {"source": "test"}

    @pytest.mark.asyncio
    async def test_append_turn_updates_metadata(self, storage: SessionStorage) -> None:
        """Appending turn updates session metadata."""
        await storage.create_session("user-1", session_id="update-test")

        before = await storage.get_metadata("update-test")
        assert before.turn_count == 0

        await storage.append_turn("user-1", "update-test", "user", "Hello")

        after = await storage.get_metadata("update-test")
        assert after.turn_count == 1
        assert after.updated_at >= before.updated_at

    @pytest.mark.asyncio
    async def test_append_turn_auto_title(self, storage: SessionStorage) -> None:
        """First user message becomes title."""
        await storage.create_session("user-1", session_id="title-test")

        await storage.append_turn(
            "user-1",
            "title-test",
            "user",
            "How do I cook pasta?",
        )

        meta = await storage.get_metadata("title-test")
        assert meta.title == "How do I cook pasta?"

    @pytest.mark.asyncio
    async def test_append_turn_auto_title_truncates(self, storage: SessionStorage) -> None:
        """Long messages are truncated in title."""
        await storage.create_session("user-1", session_id="long-title")

        long_message = "A" * 100
        await storage.append_turn("user-1", "long-title", "user", long_message)

        meta = await storage.get_metadata("long-title")
        assert len(meta.title) <= 53  # 50 chars + "..."
        assert meta.title.endswith("...")

    @pytest.mark.asyncio
    async def test_list_sessions(self, storage: SessionStorage) -> None:
        """List user sessions."""
        # Create multiple sessions
        await storage.create_session("user-1", session_id="session-1")
        await storage.create_session("user-1", session_id="session-2")
        await storage.create_session("user-2", session_id="session-3")

        # List for user-1
        sessions = await storage.list_sessions("user-1")

        assert len(sessions) == 2
        ids = {s.session_id for s in sessions}
        assert ids == {"session-1", "session-2"}

    @pytest.mark.asyncio
    async def test_list_sessions_pagination(self, storage: SessionStorage) -> None:
        """List sessions with pagination."""
        for i in range(5):
            await storage.create_session("user-1", session_id=f"session-{i}")

        # Get first 2
        page1 = await storage.list_sessions("user-1", limit=2, offset=0)
        assert len(page1) == 2

        # Get next 2
        page2 = await storage.list_sessions("user-1", limit=2, offset=2)
        assert len(page2) == 2

        # Get last 1
        page3 = await storage.list_sessions("user-1", limit=2, offset=4)
        assert len(page3) == 1

    @pytest.mark.asyncio
    async def test_list_sessions_most_recent_first(self, storage: SessionStorage) -> None:
        """Sessions are listed most recent first."""
        await storage.create_session("user-1", session_id="first")
        await storage.create_session("user-1", session_id="second")
        await storage.create_session("user-1", session_id="third")

        sessions = await storage.list_sessions("user-1")

        # Most recent first
        assert sessions[0].session_id == "third"
        assert sessions[1].session_id == "second"
        assert sessions[2].session_id == "first"

    @pytest.mark.asyncio
    async def test_delete_session(self, storage: SessionStorage) -> None:
        """Delete a session."""
        await storage.create_session("user-1", session_id="to-delete")
        await storage.append_turn("user-1", "to-delete", "user", "Hello")

        # Verify exists
        session = await storage.get_session("user-1", "to-delete")
        assert session is not None

        # Delete
        result = await storage.delete_session("user-1", "to-delete")
        assert result is True

        # Verify gone
        session = await storage.get_session("user-1", "to-delete")
        assert session is None

        # Verify not in list
        sessions = await storage.list_sessions("user-1")
        assert len(sessions) == 0

    @pytest.mark.asyncio
    async def test_delete_session_wrong_user(self, storage: SessionStorage) -> None:
        """Cannot delete another user's session."""
        await storage.create_session("user-1", session_id="protected")

        result = await storage.delete_session("user-2", "protected")
        assert result is False

        # Session still exists
        session = await storage.get_session("user-1", "protected")
        assert session is not None

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self, storage: SessionStorage) -> None:
        """Deleting non-existent session returns False."""
        result = await storage.delete_session("user-1", "nonexistent")
        assert result is False
