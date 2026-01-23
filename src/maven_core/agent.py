"""Main Agent class for maven-core."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maven_core.config import Config
from maven_core.plugins import (
    create_database,
    create_file_store,
    create_kv_store,
    create_sandbox_backend,
)
from maven_core.protocols import Database, FileStore, KVStore, SandboxBackend


@dataclass
class ChatResponse:
    """Response from a chat invocation."""

    content: str
    session_id: str
    message_id: str


@dataclass
class StreamChunk:
    """A chunk of streaming response."""

    content: str
    done: bool = False


class Agent:
    """Main Agent class for maven-core.

    Example usage:
        # Load from config file
        agent = Agent.from_config("config.yaml")

        # Start HTTP server
        agent.serve(port=8080)

        # Or use directly
        response = await agent.chat(message="Hello", user_id="user-123")

        # Streaming
        async for chunk in agent.stream(message="Hello", user_id="user-123"):
            print(chunk.content, end="")
    """

    def __init__(self, config: Config) -> None:
        """Initialize the agent with configuration.

        Use `Agent.from_config()` for convenience.
        """
        self.config = config
        self._files: FileStore | None = None
        self._kv: KVStore | None = None
        self._db: Database | None = None
        self._sandbox: SandboxBackend | None = None
        self._initialized = False

    @classmethod
    def from_config(cls, path: str | Path) -> "Agent":
        """Create an Agent from a configuration file.

        Args:
            path: Path to YAML or JSON configuration file

        Returns:
            Configured Agent instance
        """
        config = Config.from_file(path)
        return cls(config)

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> "Agent":
        """Create an Agent from a configuration dictionary.

        Args:
            config_dict: Configuration as a dictionary

        Returns:
            Configured Agent instance
        """
        config = Config.from_dict(config_dict)
        return cls(config)

    async def _ensure_initialized(self) -> None:
        """Lazily initialize backends on first use."""
        if self._initialized:
            return

        # Initialize storage backends
        files_config = self.config.storage.files
        self._files = create_file_store(
            files_config.backend,
            path=files_config.path,
            bucket=files_config.bucket,
            endpoint=files_config.endpoint,
            access_key=files_config.access_key,
            secret_key=files_config.secret_key,
        )

        kv_config = self.config.storage.kv
        self._kv = create_kv_store(
            kv_config.backend,
            namespace_id=kv_config.namespace_id,
            api_token=kv_config.api_token,
            redis_url=kv_config.redis_url,
        )

        db_config = self.config.storage.database
        self._db = create_database(
            db_config.backend,
            path=db_config.path,
            database_id=db_config.database_id,
            api_token=db_config.api_token,
            connection_string=db_config.connection_string,
        )

        sandbox_config = self.config.provisioning
        self._sandbox = create_sandbox_backend(
            sandbox_config.backend,
            account_id=sandbox_config.account_id,
            api_token=sandbox_config.api_token,
            limits=sandbox_config.limits.model_dump(),
        )

        self._initialized = True

    @property
    def files(self) -> FileStore:
        """Get the file storage backend."""
        if self._files is None:
            raise RuntimeError("Agent not initialized. Use async context manager or call chat/stream first.")
        return self._files

    @property
    def kv(self) -> KVStore:
        """Get the KV storage backend."""
        if self._kv is None:
            raise RuntimeError("Agent not initialized. Use async context manager or call chat/stream first.")
        return self._kv

    @property
    def db(self) -> Database:
        """Get the database backend."""
        if self._db is None:
            raise RuntimeError("Agent not initialized. Use async context manager or call chat/stream first.")
        return self._db

    @property
    def sandbox(self) -> SandboxBackend:
        """Get the sandbox backend."""
        if self._sandbox is None:
            raise RuntimeError("Agent not initialized. Use async context manager or call chat/stream first.")
        return self._sandbox

    async def chat(
        self,
        message: str,
        user_id: str,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a message and get a response.

        Args:
            message: The user's message
            user_id: User identifier
            session_id: Optional session ID (created if not provided)
            **kwargs: Additional options

        Returns:
            ChatResponse with the assistant's response
        """
        await self._ensure_initialized()

        # TODO: Implement full chat logic with Claude SDK
        # For now, return a placeholder response
        import uuid
        if session_id is None:
            session_id = f"session-{uuid.uuid4().hex[:8]}"

        return ChatResponse(
            content=f"Echo: {message}",
            session_id=session_id,
            message_id=f"msg-{uuid.uuid4().hex[:8]}",
        )

    async def stream(
        self,
        message: str,
        user_id: str,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Send a message and stream the response.

        Args:
            message: The user's message
            user_id: User identifier
            session_id: Optional session ID (created if not provided)
            **kwargs: Additional options

        Yields:
            StreamChunk objects with response content
        """
        await self._ensure_initialized()

        # TODO: Implement full streaming with Claude SDK
        # For now, yield a placeholder response
        for word in f"Echo: {message}".split():
            yield StreamChunk(content=word + " ")
        yield StreamChunk(content="", done=True)

    def serve(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        """Start the HTTP server.

        Args:
            host: Host to bind to (defaults to config value)
            port: Port to bind to (defaults to config value)
        """
        import uvicorn

        from maven_core.server.app import create_app

        app = create_app(self)
        uvicorn.run(
            app,
            host=host or self.config.server.host,
            port=port or self.config.server.port,
        )

    async def __aenter__(self) -> "Agent":
        """Async context manager entry."""
        await self._ensure_initialized()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit - cleanup resources."""
        # TODO: Implement cleanup for backends that need it
        pass
