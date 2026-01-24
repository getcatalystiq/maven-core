"""Main Agent class for maven-core."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maven_core.caching import TTLCache
from maven_core.config import Config
from maven_core.llm import create_llm_client
from maven_core.observability import (
    RequestContext,
    Timer,
    emit_counter,
    emit_timer,
    get_logger,
)
from maven_core.plugins import (
    create_database,
    create_file_store,
    create_kv_store,
    create_sandbox_backend,
)
from maven_core.protocols import Database, FileStore, KVStore, SandboxBackend

logger = get_logger(__name__)


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
        self._llm: Any = None
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._cache: TTLCache[str] = TTLCache(ttl_seconds=300)

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
        """Lazily initialize backends on first use.

        Uses lock to prevent concurrent initialization.
        """
        if self._initialized:
            return

        # Double-checked locking pattern
        async with self._init_lock:
            if self._initialized:
                return
            await self._do_initialize()

    async def _do_initialize(self) -> None:
        """Perform actual initialization (called under lock)."""
        with Timer() as timer:
            logger.info("Initializing agent backends")

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

            # Initialize LLM client (Claude Agent SDK)
            llm_config = self.config.llm
            self._llm = create_llm_client(
                provider=llm_config.provider,
                backend=llm_config.backend,
                model=llm_config.model,
                allowed_tools=llm_config.allowed_tools,
                cwd=llm_config.cwd,
                system_prompt=llm_config.system_prompt,
                max_turns=llm_config.max_turns,
                permission_mode=llm_config.permission_mode,
                aws_region=llm_config.aws_region,
                aws_profile=llm_config.aws_profile,
            )

            self._initialized = True

        logger.info(
            "Agent backends initialized",
            duration_ms=timer.duration_ms,
        )
        emit_timer("agent.init", timer.duration_ms)

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

    @property
    def llm(self) -> Any:
        """Get the LLM client (Claude Agent SDK)."""
        if self._llm is None:
            raise RuntimeError("Agent not initialized. Use async context manager or call chat/stream first.")
        return self._llm

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

        import uuid
        if session_id is None:
            session_id = f"session-{uuid.uuid4().hex[:8]}"

        async with RequestContext(
            user_id=user_id,
            session_id=session_id,
        ):
            with Timer() as timer:
                logger.info("Chat started", context={"message_length": len(message)})
                emit_counter("agent.chat.started")

                # Call LLM (Claude Agent SDK)
                content = await self.llm.complete(message)

                response = ChatResponse(
                    content=content,
                    session_id=session_id,
                    message_id=f"msg-{uuid.uuid4().hex[:8]}",
                )

            logger.info(
                "Chat completed",
                context={"response_length": len(response.content)},
                duration_ms=timer.duration_ms,
            )
            emit_timer("agent.chat.duration", timer.duration_ms)
            emit_counter("agent.chat.completed")

            return response

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

        import uuid
        if session_id is None:
            session_id = f"session-{uuid.uuid4().hex[:8]}"

        # Set up request context for logging
        request_id_var_token = None
        user_id_var_token = None
        session_id_var_token = None

        from maven_core.observability import request_id_var, session_id_var, user_id_var

        request_id_var_token = request_id_var.set(str(uuid.uuid4()))
        user_id_var_token = user_id_var.set(user_id)
        session_id_var_token = session_id_var.set(session_id)

        try:
            logger.info("Stream started", context={"message_length": len(message)})
            emit_counter("agent.stream.started")

            # Stream from LLM (Claude Agent SDK)
            async for event in self.llm.stream(message):
                if event.type == "text":
                    yield StreamChunk(content=event.content)
                elif event.type == "done":
                    yield StreamChunk(content="", done=True)
                elif event.type == "error":
                    raise RuntimeError(event.error or "LLM stream error")

            emit_counter("agent.stream.completed")
        except Exception as e:
            logger.error("Stream failed", error=e)
            emit_counter("agent.stream.failed")
            raise
        finally:
            # Clean up context vars - reset to previous values
            if request_id_var_token is not None:
                request_id_var.reset(request_id_var_token)
            if user_id_var_token is not None:
                user_id_var.reset(user_id_var_token)
            if session_id_var_token is not None:
                session_id_var.reset(session_id_var_token)

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
