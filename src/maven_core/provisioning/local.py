"""Local subprocess-based sandbox for development."""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from maven_core.protocols.sandbox import SandboxResult


class LocalSandbox:
    """Subprocess-based sandbox for local development.

    WARNING: NOT for production use. Provides no security isolation.
    Use Cloudflare Sandbox or Docker for production deployments.
    """

    def __init__(
        self,
        limits: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize local sandbox.

        Args:
            limits: Resource limits (timeout_seconds used, others ignored)
            **kwargs: Ignored (for compatibility with other backends)
        """
        self._limits = limits or {}
        self._timeout = self._limits.get("timeout_seconds", 30)
        self._workdirs: dict[str, Path] = {}

    async def create(self, tenant_id: str, session_id: str) -> str:
        """Create a new sandbox and return its ID."""
        sandbox_id = f"{tenant_id}-{session_id}-{uuid4().hex[:8]}"
        workdir = Path(tempfile.mkdtemp(prefix="maven-sandbox-"))
        self._workdirs[sandbox_id] = workdir
        return sandbox_id

    async def execute(
        self,
        sandbox_id: str,
        code: str,
        files: dict[str, bytes] | None = None,
    ) -> SandboxResult:
        """Execute code in a sandbox."""
        workdir = self._workdirs.get(sandbox_id)
        if workdir is None:
            return SandboxResult(
                stdout="",
                stderr=f"Sandbox not found: {sandbox_id}",
                exit_code=-1,
                files={},
            )

        # Write input files
        for name, content in (files or {}).items():
            file_path = workdir / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)

        # Write the code to execute
        script_path = workdir / "script.py"
        script_path.write_text(code)

        # Execute the script
        proc = await asyncio.create_subprocess_exec(
            "python",
            str(script_path),
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                stdout="",
                stderr=f"Execution timed out after {self._timeout} seconds",
                exit_code=-1,
                files={},
            )

        # Collect output files (exclude the script itself)
        output_files: dict[str, bytes] = {}
        for file_path in workdir.rglob("*"):
            if file_path.is_file() and file_path.name != "script.py":
                relative_path = str(file_path.relative_to(workdir))
                output_files[relative_path] = file_path.read_bytes()

        return SandboxResult(
            stdout=stdout.decode() if stdout else "",
            stderr=stderr.decode() if stderr else "",
            exit_code=proc.returncode or 0,
            files=output_files,
        )

    async def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox and clean up resources."""
        workdir = self._workdirs.pop(sandbox_id, None)
        if workdir and workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)
