"""Sandbox protocol for code execution backends."""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SandboxResult:
    """Result from sandbox code execution."""

    stdout: str
    stderr: str
    exit_code: int
    files: dict[str, bytes]


class SandboxBackend(Protocol):
    """Protocol for sandbox/code execution backends (Cloudflare Sandbox, Docker, subprocess)."""

    async def create(self, tenant_id: str, session_id: str) -> str:
        """Create a new sandbox and return its ID."""
        ...

    async def execute(
        self,
        sandbox_id: str,
        code: str,
        files: dict[str, bytes] | None = None,
    ) -> SandboxResult:
        """Execute code in a sandbox and return the result."""
        ...

    async def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox and clean up resources."""
        ...
