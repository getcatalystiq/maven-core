"""Claude Agent SDK client for maven-core."""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

from maven_core.llm.base import StreamEvent


class ClaudeClient:
    """Claude Agent SDK client.

    Wraps the Claude Agent SDK to provide chat and streaming capabilities
    with full access to Claude Code's tools and agentic features.

    Supports multiple backends:
    - anthropic: Direct Anthropic API (requires ANTHROPIC_API_KEY)
    - bedrock: AWS Bedrock (requires AWS credentials)
    - vertex: Google Vertex AI (requires GCP credentials)

    Example:
        # Using Anthropic API
        client = ClaudeClient(
            backend="anthropic",
            allowed_tools=["Read", "Write", "Bash"],
        )

        # Using AWS Bedrock
        client = ClaudeClient(
            backend="bedrock",
            model="us.anthropic.claude-sonnet-4-20250514-v1:0",
            aws_region="us-east-1",
        )

        response = await client.complete("What files are in this directory?")
    """

    def __init__(
        self,
        backend: str = "anthropic",
        model: str | None = None,
        allowed_tools: list[str] | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        max_turns: int | None = None,
        permission_mode: str = "default",
        mcp_servers: dict[str, Any] | None = None,
        aws_region: str | None = None,
        aws_profile: str | None = None,
    ) -> None:
        """Initialize Claude client.

        Args:
            backend: API backend ("anthropic", "bedrock", or "vertex")
            model: Model ID (e.g., "us.anthropic.claude-sonnet-4-20250514-v1:0" for Bedrock)
            allowed_tools: List of tools Claude can use (e.g., ["Read", "Write", "Bash"])
            cwd: Working directory for file operations
            system_prompt: Custom system prompt
            max_turns: Maximum conversation turns (None for unlimited)
            permission_mode: Permission mode ("default", "acceptEdits", "bypassPermissions")
            mcp_servers: Additional MCP servers to connect
            aws_region: AWS region for Bedrock
            aws_profile: AWS profile for Bedrock credentials
        """
        self.backend = backend
        self.model = model
        self.allowed_tools = allowed_tools
        self.cwd = Path(cwd) if cwd else None
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        self.permission_mode = permission_mode
        self.mcp_servers = mcp_servers or {}
        self.aws_region = aws_region
        self.aws_profile = aws_profile

        # Configure backend via environment variables
        self._configure_backend()

    def _configure_backend(self) -> None:
        """Configure Claude Agent SDK backend via environment variables.

        The Claude Agent SDK uses environment variables to select the backend:
        - ANTHROPIC_API_KEY: Direct Anthropic API (default)
        - CLAUDE_CODE_USE_BEDROCK=1: Use AWS Bedrock
        - CLAUDE_CODE_USE_VERTEX=1: Use Google Vertex AI
        """
        if self.backend == "bedrock":
            os.environ["CLAUDE_CODE_USE_BEDROCK"] = "1"
            if self.aws_region:
                os.environ["AWS_REGION"] = self.aws_region
            if self.aws_profile:
                os.environ["AWS_PROFILE"] = self.aws_profile
            if self.model:
                os.environ["CLAUDE_CODE_BEDROCK_MODEL"] = self.model
        elif self.backend == "vertex":
            os.environ["CLAUDE_CODE_USE_VERTEX"] = "1"
            if self.model:
                os.environ["CLAUDE_CODE_VERTEX_MODEL"] = self.model
        # For "anthropic" backend, just ensure ANTHROPIC_API_KEY is set (user's responsibility)

    def _build_options(self) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions from configuration."""
        kwargs: dict[str, Any] = {}

        if self.allowed_tools:
            kwargs["allowed_tools"] = self.allowed_tools

        if self.cwd:
            kwargs["cwd"] = self.cwd

        if self.system_prompt:
            kwargs["system_prompt"] = self.system_prompt

        if self.max_turns is not None:
            kwargs["max_turns"] = self.max_turns

        if self.permission_mode != "default":
            kwargs["permission_mode"] = self.permission_mode

        if self.mcp_servers:
            kwargs["mcp_servers"] = self.mcp_servers

        return ClaudeAgentOptions(**kwargs)

    async def complete(self, prompt: str) -> str:
        """Generate a completion for the given prompt.

        Args:
            prompt: The user's message

        Returns:
            The assistant's response text
        """
        options = self._build_options()
        full_response = ""

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        full_response += block.text

        return full_response

    async def stream(self, prompt: str) -> AsyncIterator[StreamEvent]:
        """Stream a completion for the given prompt.

        Args:
            prompt: The user's message

        Yields:
            StreamEvent objects with content chunks and tool usage
        """
        options = self._build_options()

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield StreamEvent(type="text", content=block.text)

                    elif isinstance(block, ToolUseBlock):
                        yield StreamEvent(
                            type="tool_use",
                            tool_name=block.name,
                            tool_input=block.input,
                        )

                    elif isinstance(block, ToolResultBlock):
                        content = ""
                        if block.content:
                            for item in block.content:
                                if hasattr(item, "text"):
                                    content += item.text
                        yield StreamEvent(
                            type="tool_result",
                            content=content,
                            tool_name=block.tool_use_id,
                        )

        yield StreamEvent(type="done")

    async def close(self) -> None:
        """Clean up resources (no-op for stateless query API)."""
        pass


class ClaudeSessionClient:
    """Claude Agent SDK session client for multi-turn conversations.

    Uses ClaudeSDKClient for bidirectional, interactive conversations
    with support for custom tools and hooks.

    Example:
        async with ClaudeSessionClient() as client:
            response = await client.send("Hello")
            print(response)

            response = await client.send("What did I just say?")
            print(response)
    """

    def __init__(
        self,
        allowed_tools: list[str] | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        mcp_servers: dict[str, Any] | None = None,
        hooks: dict[str, Any] | None = None,
    ) -> None:
        """Initialize session client.

        Args:
            allowed_tools: List of tools Claude can use
            cwd: Working directory for file operations
            system_prompt: Custom system prompt
            mcp_servers: Additional MCP servers (can include SDK MCP servers)
            hooks: Hook configurations for permission control
        """
        self.allowed_tools = allowed_tools
        self.cwd = Path(cwd) if cwd else None
        self.system_prompt = system_prompt
        self.mcp_servers = mcp_servers or {}
        self.hooks = hooks or {}
        self._client: ClaudeSDKClient | None = None

    def _build_options(self) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions from configuration."""
        kwargs: dict[str, Any] = {}

        if self.allowed_tools:
            kwargs["allowed_tools"] = self.allowed_tools

        if self.cwd:
            kwargs["cwd"] = self.cwd

        if self.system_prompt:
            kwargs["system_prompt"] = self.system_prompt

        if self.mcp_servers:
            kwargs["mcp_servers"] = self.mcp_servers

        if self.hooks:
            kwargs["hooks"] = self.hooks

        return ClaudeAgentOptions(**kwargs)

    async def __aenter__(self) -> "ClaudeSessionClient":
        """Enter async context and start session."""
        options = self._build_options()
        self._client = ClaudeSDKClient(options=options)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context and clean up."""
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)
            self._client = None

    async def send(self, prompt: str) -> str:
        """Send a message and get a response.

        Args:
            prompt: The user's message

        Returns:
            The assistant's response text
        """
        if not self._client:
            raise RuntimeError("Session not started. Use async context manager.")

        await self._client.query(prompt)

        full_response = ""
        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        full_response += block.text

        return full_response

    async def stream(self, prompt: str) -> AsyncIterator[StreamEvent]:
        """Send a message and stream the response.

        Args:
            prompt: The user's message

        Yields:
            StreamEvent objects with content chunks
        """
        if not self._client:
            raise RuntimeError("Session not started. Use async context manager.")

        await self._client.query(prompt)

        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield StreamEvent(type="text", content=block.text)

                    elif isinstance(block, ToolUseBlock):
                        yield StreamEvent(
                            type="tool_use",
                            tool_name=block.name,
                            tool_input=block.input,
                        )

        yield StreamEvent(type="done")
