"""Factory function for creating LLM clients."""

from pathlib import Path
from typing import Any


def create_llm_client(
    provider: str = "claude",
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
    **kwargs: Any,
) -> Any:
    """Create an LLM client based on provider.

    Args:
        provider: Provider name ("claude" or "mock")
        backend: API backend ("anthropic", "bedrock", or "vertex")
        model: Model ID (auto-detected if not set)
        allowed_tools: List of tools Claude can use
        cwd: Working directory for file operations
        system_prompt: Custom system prompt
        max_turns: Maximum conversation turns
        permission_mode: Permission mode for tool use
        mcp_servers: Additional MCP servers
        aws_region: AWS region for Bedrock
        aws_profile: AWS profile for Bedrock credentials
        **kwargs: Additional provider-specific options

    Returns:
        Configured LLM client

    Raises:
        ValueError: If provider is unknown
    """
    if provider == "claude":
        from maven_core.llm.claude import ClaudeClient

        return ClaudeClient(
            backend=backend,
            model=model,
            allowed_tools=allowed_tools,
            cwd=cwd,
            system_prompt=system_prompt,
            max_turns=max_turns,
            permission_mode=permission_mode,
            mcp_servers=mcp_servers,
            aws_region=aws_region,
            aws_profile=aws_profile,
        )

    elif provider == "mock":
        from maven_core.llm.mock import MockClaudeClient

        return MockClaudeClient(
            allowed_tools=allowed_tools,
            cwd=cwd,
            system_prompt=system_prompt,
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Use 'claude' or 'mock'.")
