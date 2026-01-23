"""Cloudflare Sandbox backend.

This module requires the Cloudflare Sandbox SDK to be available.
The actual implementation runs inside a Cloudflare Durable Object.
"""

from typing import Any

from maven_core.protocols.sandbox import SandboxResult


class CloudflareSandbox:
    """Cloudflare Sandbox backend.

    This is a placeholder for the Cloudflare Sandbox SDK integration.
    In production, sandboxes are created from within Durable Objects using
    `this.ctx.container.spawn()`.

    This class is used when running in standalone mode and calling out to
    a Cloudflare Worker that manages sandbox lifecycle.
    """

    def __init__(
        self,
        account_id: str | None = None,
        api_token: str | None = None,
        limits: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Cloudflare Sandbox backend.

        Args:
            account_id: Cloudflare account ID
            api_token: Cloudflare API token
            limits: Resource limits (cpu_ms, memory_mb, timeout_seconds)
            **kwargs: Additional configuration
        """
        if not account_id or not api_token:
            raise ValueError(
                "Cloudflare Sandbox requires account_id and api_token. "
                "Use 'local' backend for development."
            )

        self.account_id = account_id
        self.api_token = api_token
        self._limits = limits or {}

    async def create(self, tenant_id: str, session_id: str) -> str:
        """Create a new sandbox and return its ID.

        In Cloudflare deployment, this is called from the Durable Object.
        """
        # TODO: Implement Cloudflare Sandbox SDK integration
        # This would call out to a Worker endpoint that creates the sandbox
        raise NotImplementedError(
            "Cloudflare Sandbox SDK integration not yet implemented. "
            "Use 'local' backend for development."
        )

    async def execute(
        self,
        sandbox_id: str,
        code: str,
        files: dict[str, bytes] | None = None,
    ) -> SandboxResult:
        """Execute code in a sandbox."""
        # TODO: Implement Cloudflare Sandbox SDK integration
        raise NotImplementedError(
            "Cloudflare Sandbox SDK integration not yet implemented. "
            "Use 'local' backend for development."
        )

    async def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox and clean up resources."""
        # TODO: Implement Cloudflare Sandbox SDK integration
        raise NotImplementedError(
            "Cloudflare Sandbox SDK integration not yet implemented. "
            "Use 'local' backend for development."
        )
