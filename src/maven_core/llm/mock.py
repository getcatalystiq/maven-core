"""Mock LLM client for testing."""

from collections.abc import AsyncIterator
from pathlib import Path

from maven_core.llm.base import StreamEvent


class MockClaudeClient:
    """Mock Claude client that echoes messages.

    Used for testing without requiring Claude Code CLI.
    """

    def __init__(
        self,
        allowed_tools: list[str] | None = None,
        cwd: str | Path | None = None,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> None:
        self.allowed_tools = allowed_tools
        self.cwd = Path(cwd) if isinstance(cwd, str) else cwd
        self.system_prompt = system_prompt

    async def complete(self, prompt: str) -> str:
        """Return echo of the prompt."""
        return f"Echo: {prompt}"

    async def stream(self, prompt: str) -> AsyncIterator[StreamEvent]:
        """Stream echo of the prompt."""
        content = f"Echo: {prompt}"

        # Stream word by word
        words = content.split()
        for word in words:
            yield StreamEvent(type="text", content=word + " ")

        yield StreamEvent(type="done", usage={"input_tokens": 10, "output_tokens": len(words)})

    async def close(self) -> None:
        """No-op for mock client."""
        pass
