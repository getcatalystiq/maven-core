"""Session manager for conversation management."""

from dataclasses import dataclass
from typing import Any

from maven_core.protocols import FileStore, KVStore
from maven_core.sessions.storage import (
    Session,
    SessionMetadata,
    SessionStorage,
    Turn,
)


@dataclass
class ConversationContext:
    """Context for a conversation, including recent turns."""

    session_id: str
    user_id: str
    turns: list[Turn]
    metadata: dict[str, Any]


class SessionManager:
    """High-level session management.

    Wraps SessionStorage with additional functionality:
    - Context window management
    - Turn summarization (future)
    - Export formats
    """

    def __init__(
        self,
        files: FileStore,
        kv: KVStore,
        tenant_id: str,
        max_context_turns: int = 50,
    ) -> None:
        """Initialize session manager.

        Args:
            files: File storage backend
            kv: KV storage backend
            tenant_id: Current tenant ID
            max_context_turns: Maximum turns to include in context
        """
        self.storage = SessionStorage(files, kv, tenant_id)
        self.tenant_id = tenant_id
        self.max_context_turns = max_context_turns

    async def get_or_create_session(
        self,
        user_id: str,
        session_id: str | None = None,
    ) -> SessionMetadata:
        """Get existing session or create new one.

        Args:
            user_id: User ID
            session_id: Optional session ID

        Returns:
            Session metadata
        """
        if session_id:
            meta = await self.storage.get_metadata(session_id)
            if meta and meta.user_id == user_id:
                return meta

        return await self.storage.create_session(user_id, session_id)

    async def get_context(
        self,
        user_id: str,
        session_id: str,
    ) -> ConversationContext:
        """Get conversation context for LLM.

        Args:
            user_id: User ID
            session_id: Session ID

        Returns:
            Conversation context with recent turns
        """
        session = await self.storage.get_session(user_id, session_id)

        if not session:
            # Create new session
            meta = await self.storage.create_session(user_id, session_id)
            return ConversationContext(
                session_id=session_id,
                user_id=user_id,
                turns=[],
                metadata={},
            )

        # Get recent turns (within context window)
        turns = session.turns[-self.max_context_turns:]

        return ConversationContext(
            session_id=session_id,
            user_id=user_id,
            turns=turns,
            metadata={
                "title": session.metadata.title,
                "created_at": session.metadata.created_at,
                "turn_count": session.metadata.turn_count,
            },
        )

    async def add_user_message(
        self,
        user_id: str,
        session_id: str,
        content: str,
    ) -> Turn:
        """Add a user message to the session.

        Args:
            user_id: User ID
            session_id: Session ID
            content: Message content

        Returns:
            The created turn
        """
        return await self.storage.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="user",
            content=content,
        )

    async def add_assistant_message(
        self,
        user_id: str,
        session_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Turn:
        """Add an assistant message to the session.

        Args:
            user_id: User ID
            session_id: Session ID
            content: Message content
            metadata: Optional metadata (tokens, model, etc.)

        Returns:
            The created turn
        """
        return await self.storage.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=content,
            metadata=metadata,
        )

    async def list_sessions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SessionMetadata]:
        """List user's sessions.

        Args:
            user_id: User ID
            limit: Maximum sessions to return
            offset: Number to skip

        Returns:
            List of session metadata
        """
        return await self.storage.list_sessions(user_id, limit, offset)

    async def get_session(
        self,
        user_id: str,
        session_id: str,
    ) -> Session | None:
        """Get complete session with all turns.

        Args:
            user_id: User ID
            session_id: Session ID

        Returns:
            Session or None if not found
        """
        return await self.storage.get_session(user_id, session_id)

    async def delete_session(
        self,
        user_id: str,
        session_id: str,
    ) -> bool:
        """Delete a session.

        Args:
            user_id: User ID
            session_id: Session ID

        Returns:
            True if deleted
        """
        return await self.storage.delete_session(user_id, session_id)

    async def export_session(
        self,
        user_id: str,
        session_id: str,
        format: str = "json",
    ) -> str:
        """Export session transcript.

        Args:
            user_id: User ID
            session_id: Session ID
            format: Export format ("json" or "markdown")

        Returns:
            Exported transcript
        """
        session = await self.storage.get_session(user_id, session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if format == "json":
            import json
            return json.dumps({
                "session_id": session.metadata.session_id,
                "title": session.metadata.title,
                "created_at": session.metadata.created_at,
                "turns": [t.to_dict() for t in session.turns],
            }, indent=2)

        elif format == "markdown":
            lines = [f"# {session.metadata.title or 'Conversation'}\n"]
            for turn in session.turns:
                role = "**User**" if turn.role == "user" else "**Assistant**"
                lines.append(f"{role}:\n\n{turn.content}\n")
            return "\n".join(lines)

        else:
            raise ValueError(f"Unknown format: {format}")
