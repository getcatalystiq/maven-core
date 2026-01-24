"""Two-tier session storage: files for content, KV for metadata."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from maven_core.protocols import FileStore, KVStore


@dataclass
class Turn:
    """A single turn in a conversation."""

    id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Turn":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            role=data["role"],
            content=data["content"],
            timestamp=data["timestamp"],
            metadata=data.get("metadata", {}),
        )


@dataclass
class SessionMetadata:
    """Session metadata stored in KV."""

    session_id: str
    tenant_id: str
    user_id: str
    created_at: float
    updated_at: float
    turn_count: int
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turn_count": self.turn_count,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMetadata":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            tenant_id=data["tenant_id"],
            user_id=data["user_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            turn_count=data["turn_count"],
            title=data.get("title"),
        )


@dataclass
class Session:
    """Complete session with metadata and turns."""

    metadata: SessionMetadata
    turns: list[Turn] = field(default_factory=list)


class SessionStorage:
    """Two-tier storage for sessions.

    - Metadata (session list, last updated) -> KV for fast queries
    - Content (full transcript) -> FileStore for large data
    """

    def __init__(
        self,
        files: FileStore,
        kv: KVStore,
        tenant_id: str,
    ) -> None:
        """Initialize session storage.

        Args:
            files: File storage for transcripts
            kv: KV storage for metadata
            tenant_id: Current tenant ID
        """
        self.files = files
        self.kv = kv
        self.tenant_id = tenant_id
        # Lock for session operations to prevent race conditions
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    async def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific session."""
        async with self._locks_lock:
            if session_id not in self._session_locks:
                self._session_locks[session_id] = asyncio.Lock()
            return self._session_locks[session_id]

    def _transcript_key(self, user_id: str, session_id: str) -> str:
        """Get file key for session transcript."""
        return f"transcripts/{self.tenant_id}/{user_id}/{session_id}.json"

    def _metadata_key(self, session_id: str) -> str:
        """Get KV key for session metadata."""
        return f"session:{self.tenant_id}:{session_id}"

    def _user_sessions_key(self, user_id: str) -> str:
        """Get KV key for user's session list."""
        return f"user_sessions:{self.tenant_id}:{user_id}"

    async def create_session(
        self,
        user_id: str,
        session_id: str | None = None,
        title: str | None = None,
    ) -> SessionMetadata:
        """Create a new session.

        Args:
            user_id: User ID
            session_id: Optional session ID (generated if not provided)
            title: Optional session title

        Returns:
            Session metadata
        """
        if session_id is None:
            session_id = f"session-{uuid4().hex[:12]}"

        now = time.time()
        metadata = SessionMetadata(
            session_id=session_id,
            tenant_id=self.tenant_id,
            user_id=user_id,
            created_at=now,
            updated_at=now,
            turn_count=0,
            title=title,
        )

        # Save metadata to KV
        await self.kv.set(
            self._metadata_key(session_id),
            json.dumps(metadata.to_dict()).encode(),
        )

        # Add to user's session list
        await self._add_to_user_sessions(user_id, session_id)

        # Create empty transcript file
        await self.files.put(
            self._transcript_key(user_id, session_id),
            json.dumps({"turns": []}).encode(),
            content_type="application/json",
        )

        return metadata

    async def _add_to_user_sessions(self, user_id: str, session_id: str) -> None:
        """Add session to user's session list."""
        key = self._user_sessions_key(user_id)
        existing = await self.kv.get(key)

        if existing:
            sessions = json.loads(existing.decode())
        else:
            sessions = []

        if session_id not in sessions:
            sessions.insert(0, session_id)  # Most recent first
            await self.kv.set(key, json.dumps(sessions).encode())

    async def get_session(self, user_id: str, session_id: str) -> Session | None:
        """Get a complete session with all turns.

        Args:
            user_id: User ID
            session_id: Session ID

        Returns:
            Session with metadata and turns, or None if not found
        """
        # Get metadata
        meta_data = await self.kv.get(self._metadata_key(session_id))
        if not meta_data:
            return None

        metadata = SessionMetadata.from_dict(json.loads(meta_data.decode()))

        # Verify user owns this session
        if metadata.user_id != user_id:
            return None

        # Get transcript
        result = await self.files.get(self._transcript_key(user_id, session_id))
        if not result:
            return Session(metadata=metadata, turns=[])

        content, _ = result
        transcript = json.loads(content.decode())
        turns = [Turn.from_dict(t) for t in transcript.get("turns", [])]

        return Session(metadata=metadata, turns=turns)

    async def get_metadata(self, session_id: str) -> SessionMetadata | None:
        """Get session metadata only (no turns).

        Args:
            session_id: Session ID

        Returns:
            Session metadata or None if not found
        """
        data = await self.kv.get(self._metadata_key(session_id))
        if not data:
            return None
        return SessionMetadata.from_dict(json.loads(data.decode()))

    async def append_turn(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Turn:
        """Append a turn to a session.

        Uses locking to prevent race conditions during read-modify-write.

        Args:
            user_id: User ID
            session_id: Session ID
            role: Turn role ("user" or "assistant")
            content: Turn content
            metadata: Optional turn metadata

        Returns:
            The created turn
        """
        # Get session-specific lock to prevent race conditions
        session_lock = await self._get_session_lock(session_id)

        async with session_lock:
            now = time.time()
            turn = Turn(
                id=f"turn-{uuid4().hex[:8]}",
                role=role,
                content=content,
                timestamp=now,
                metadata=metadata or {},
            )

            # Load existing transcript (inside lock to prevent TOCTOU)
            result = await self.files.get(self._transcript_key(user_id, session_id))
            if result:
                transcript_data, _ = result
                transcript = json.loads(transcript_data.decode())
            else:
                transcript = {"turns": []}

            # Append turn
            transcript["turns"].append(turn.to_dict())

            # Save transcript
            await self.files.put(
                self._transcript_key(user_id, session_id),
                json.dumps(transcript).encode(),
                content_type="application/json",
            )

            # Update metadata
            session_meta = await self.get_metadata(session_id)
            if session_meta:
                session_meta.updated_at = now
                session_meta.turn_count = len(transcript["turns"])

                # Auto-generate title from first user message
                if session_meta.title is None and role == "user":
                    session_meta.title = content[:50] + ("..." if len(content) > 50 else "")

                await self.kv.set(
                    self._metadata_key(session_id),
                    json.dumps(session_meta.to_dict()).encode(),
                )

            return turn

    async def list_sessions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SessionMetadata]:
        """List sessions for a user.

        Uses batch fetching to avoid N+1 query pattern.

        Args:
            user_id: User ID
            limit: Maximum sessions to return
            offset: Number of sessions to skip

        Returns:
            List of session metadata, most recent first
        """
        # Get user's session list from KV
        sessions_data = await self.kv.get(self._user_sessions_key(user_id))
        if not sessions_data:
            return []

        session_ids = json.loads(sessions_data.decode())

        # Apply pagination
        session_ids = session_ids[offset:offset + limit]

        if not session_ids:
            return []

        # Batch fetch metadata for all sessions concurrently
        # This avoids the N+1 query pattern by fetching in parallel
        async def fetch_metadata(session_id: str) -> SessionMetadata | None:
            return await self.get_metadata(session_id)

        # Use asyncio.gather for parallel fetching
        results = await asyncio.gather(
            *[fetch_metadata(sid) for sid in session_ids],
            return_exceptions=True,
        )

        # Filter out None results and exceptions
        return [
            meta for meta in results
            if isinstance(meta, SessionMetadata)
        ]

    async def delete_session(self, user_id: str, session_id: str) -> bool:
        """Delete a session.

        Args:
            user_id: User ID
            session_id: Session ID

        Returns:
            True if deleted, False if not found
        """
        # Acquire lock first to prevent race conditions during deletion
        session_lock = await self._get_session_lock(session_id)

        async with session_lock:
            # Verify ownership (inside lock to prevent TOCTOU)
            meta = await self.get_metadata(session_id)
            if not meta or meta.user_id != user_id:
                return False

            # Delete transcript
            await self.files.delete(self._transcript_key(user_id, session_id))

            # Delete metadata
            await self.kv.delete(self._metadata_key(session_id))

            # Remove from user's session list
            sessions_data = await self.kv.get(self._user_sessions_key(user_id))
            if sessions_data:
                sessions = json.loads(sessions_data.decode())
                if session_id in sessions:
                    sessions.remove(session_id)
                    await self.kv.set(
                        self._user_sessions_key(user_id),
                        json.dumps(sessions).encode(),
                    )

        # Clean up session lock to prevent memory leak (outside the lock)
        async with self._locks_lock:
            self._session_locks.pop(session_id, None)

        return True
