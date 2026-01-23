"""Tests for session manager."""

import pytest

from maven_core.backends.files.local import LocalFileStore
from maven_core.backends.kv.memory import MemoryKVStore
from maven_core.sessions.manager import ConversationContext, SessionManager


@pytest.fixture
def file_store(tmp_path) -> LocalFileStore:
    """Create a local file store for testing."""
    return LocalFileStore(tmp_path)


@pytest.fixture
def kv_store() -> MemoryKVStore:
    """Create a memory KV store for testing."""
    return MemoryKVStore()


@pytest.fixture
def manager(file_store, kv_store) -> SessionManager:
    """Create session manager for testing."""
    return SessionManager(file_store, kv_store, "test-tenant", max_context_turns=10)


class TestSessionManager:
    """Tests for SessionManager."""

    @pytest.mark.asyncio
    async def test_get_or_create_session_new(self, manager: SessionManager) -> None:
        """Create new session when none exists."""
        meta = await manager.get_or_create_session("user-1")

        assert meta.session_id.startswith("session-")
        assert meta.user_id == "user-1"

    @pytest.mark.asyncio
    async def test_get_or_create_session_existing(self, manager: SessionManager) -> None:
        """Get existing session by ID."""
        # Create first
        created = await manager.get_or_create_session("user-1", session_id="existing")

        # Get same session
        retrieved = await manager.get_or_create_session("user-1", session_id="existing")

        assert retrieved.session_id == created.session_id

    @pytest.mark.asyncio
    async def test_get_or_create_session_wrong_user(self, manager: SessionManager) -> None:
        """Cannot get another user's session."""
        await manager.get_or_create_session("user-1", session_id="user1-session")

        # Different user trying to get same session gets a new one
        result = await manager.get_or_create_session("user-2", session_id="user1-session")

        # Should create new session, not return user-1's session
        assert result.user_id == "user-2"

    @pytest.mark.asyncio
    async def test_get_context_new_session(self, manager: SessionManager) -> None:
        """Get context for new session."""
        ctx = await manager.get_context("user-1", "new-session")

        assert ctx.session_id == "new-session"
        assert ctx.user_id == "user-1"
        assert ctx.turns == []
        assert ctx.metadata == {}

    @pytest.mark.asyncio
    async def test_get_context_with_turns(self, manager: SessionManager) -> None:
        """Get context includes recent turns."""
        await manager.get_or_create_session("user-1", session_id="with-turns")
        await manager.add_user_message("user-1", "with-turns", "Hello")
        await manager.add_assistant_message("user-1", "with-turns", "Hi there!")

        ctx = await manager.get_context("user-1", "with-turns")

        assert len(ctx.turns) == 2
        assert ctx.turns[0].role == "user"
        assert ctx.turns[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_get_context_truncates(self, manager: SessionManager) -> None:
        """Context is limited to max_context_turns."""
        # Manager has max_context_turns=10
        await manager.get_or_create_session("user-1", session_id="many-turns")

        # Add 15 turns
        for i in range(15):
            await manager.add_user_message("user-1", "many-turns", f"Message {i}")

        ctx = await manager.get_context("user-1", "many-turns")

        # Should only have last 10
        assert len(ctx.turns) == 10
        assert ctx.turns[0].content == "Message 5"
        assert ctx.turns[-1].content == "Message 14"

    @pytest.mark.asyncio
    async def test_add_user_message(self, manager: SessionManager) -> None:
        """Add user message to session."""
        await manager.get_or_create_session("user-1", session_id="user-msg")

        turn = await manager.add_user_message("user-1", "user-msg", "Hello!")

        assert turn.role == "user"
        assert turn.content == "Hello!"

    @pytest.mark.asyncio
    async def test_add_assistant_message(self, manager: SessionManager) -> None:
        """Add assistant message with metadata."""
        await manager.get_or_create_session("user-1", session_id="asst-msg")

        turn = await manager.add_assistant_message(
            "user-1",
            "asst-msg",
            "Hello!",
            metadata={"model": "claude-3", "tokens": 5},
        )

        assert turn.role == "assistant"
        assert turn.content == "Hello!"
        assert turn.metadata["model"] == "claude-3"
        assert turn.metadata["tokens"] == 5

    @pytest.mark.asyncio
    async def test_list_sessions(self, manager: SessionManager) -> None:
        """List user sessions."""
        await manager.get_or_create_session("user-1", session_id="session-1")
        await manager.get_or_create_session("user-1", session_id="session-2")

        sessions = await manager.list_sessions("user-1")

        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_get_session(self, manager: SessionManager) -> None:
        """Get complete session."""
        await manager.get_or_create_session("user-1", session_id="complete")
        await manager.add_user_message("user-1", "complete", "Hi")
        await manager.add_assistant_message("user-1", "complete", "Hello!")

        session = await manager.get_session("user-1", "complete")

        assert session is not None
        assert session.metadata.session_id == "complete"
        assert len(session.turns) == 2

    @pytest.mark.asyncio
    async def test_delete_session(self, manager: SessionManager) -> None:
        """Delete a session."""
        await manager.get_or_create_session("user-1", session_id="to-delete")

        result = await manager.delete_session("user-1", "to-delete")

        assert result is True

        session = await manager.get_session("user-1", "to-delete")
        assert session is None

    @pytest.mark.asyncio
    async def test_export_session_json(self, manager: SessionManager) -> None:
        """Export session as JSON."""
        await manager.get_or_create_session("user-1", session_id="export-json")
        await manager.add_user_message("user-1", "export-json", "Hello")
        await manager.add_assistant_message("user-1", "export-json", "Hi!")

        export = await manager.export_session("user-1", "export-json", format="json")

        import json
        data = json.loads(export)

        assert data["session_id"] == "export-json"
        assert len(data["turns"]) == 2

    @pytest.mark.asyncio
    async def test_export_session_markdown(self, manager: SessionManager) -> None:
        """Export session as Markdown."""
        await manager.get_or_create_session("user-1", session_id="export-md")
        await manager.add_user_message("user-1", "export-md", "What is Python?")
        await manager.add_assistant_message(
            "user-1", "export-md", "Python is a programming language."
        )

        export = await manager.export_session("user-1", "export-md", format="markdown")

        assert "**User**:" in export
        assert "What is Python?" in export
        assert "**Assistant**:" in export
        assert "Python is a programming language." in export

    @pytest.mark.asyncio
    async def test_export_session_not_found(self, manager: SessionManager) -> None:
        """Export non-existent session raises error."""
        with pytest.raises(ValueError, match="Session not found"):
            await manager.export_session("user-1", "nonexistent", format="json")

    @pytest.mark.asyncio
    async def test_export_session_invalid_format(self, manager: SessionManager) -> None:
        """Export with invalid format raises error."""
        await manager.get_or_create_session("user-1", session_id="bad-format")

        with pytest.raises(ValueError, match="Unknown format"):
            await manager.export_session("user-1", "bad-format", format="xml")
