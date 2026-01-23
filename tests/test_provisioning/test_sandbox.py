"""Tests for sandbox implementations."""

import pytest

from maven_core.provisioning.local import LocalSandbox
from maven_core.provisioning.cloudflare import CloudflareSandbox


class TestLocalSandbox:
    """Tests for LocalSandbox."""

    @pytest.fixture
    def sandbox(self) -> LocalSandbox:
        """Create a local sandbox."""
        return LocalSandbox(limits={"timeout_seconds": 5})

    @pytest.mark.asyncio
    async def test_create_sandbox(self, sandbox: LocalSandbox) -> None:
        """Create a new sandbox."""
        sandbox_id = await sandbox.create("tenant-1", "session-1")

        assert sandbox_id.startswith("tenant-1-session-1-")
        assert sandbox_id in sandbox._workdirs

    @pytest.mark.asyncio
    async def test_execute_simple_code(self, sandbox: LocalSandbox) -> None:
        """Execute simple Python code."""
        sandbox_id = await sandbox.create("tenant", "session")

        result = await sandbox.execute(sandbox_id, 'print("Hello, World!")')

        assert result.stdout.strip() == "Hello, World!"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_with_input_files(self, sandbox: LocalSandbox) -> None:
        """Execute code with input files."""
        sandbox_id = await sandbox.create("tenant", "session")

        code = """
with open('input.txt', 'r') as f:
    content = f.read()
print(content)
"""
        result = await sandbox.execute(
            sandbox_id,
            code,
            files={"input.txt": b"File content here"},
        )

        assert "File content here" in result.stdout
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_execute_with_output_files(self, sandbox: LocalSandbox) -> None:
        """Execute code that creates output files."""
        sandbox_id = await sandbox.create("tenant", "session")

        code = """
with open('output.txt', 'w') as f:
    f.write('Generated output')
print('Done')
"""
        result = await sandbox.execute(sandbox_id, code)

        assert result.exit_code == 0
        assert "output.txt" in result.files
        assert result.files["output.txt"] == b"Generated output"

    @pytest.mark.asyncio
    async def test_execute_syntax_error(self, sandbox: LocalSandbox) -> None:
        """Execute code with syntax error."""
        sandbox_id = await sandbox.create("tenant", "session")

        result = await sandbox.execute(sandbox_id, "def broken(")

        assert result.exit_code != 0
        assert "SyntaxError" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_runtime_error(self, sandbox: LocalSandbox) -> None:
        """Execute code with runtime error."""
        sandbox_id = await sandbox.create("tenant", "session")

        result = await sandbox.execute(sandbox_id, "undefined_variable")

        assert result.exit_code != 0
        assert "NameError" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_timeout(self) -> None:
        """Execute code that times out."""
        sandbox = LocalSandbox(limits={"timeout_seconds": 1})
        sandbox_id = await sandbox.create("tenant", "session")

        code = """
import time
time.sleep(10)
print('Should not reach here')
"""
        result = await sandbox.execute(sandbox_id, code)

        assert result.exit_code == -1
        assert "timed out" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_invalid_sandbox(self, sandbox: LocalSandbox) -> None:
        """Execute on non-existent sandbox."""
        result = await sandbox.execute("invalid-sandbox", 'print("test")')

        assert result.exit_code == -1
        assert "not found" in result.stderr

    @pytest.mark.asyncio
    async def test_destroy_sandbox(self, sandbox: LocalSandbox) -> None:
        """Destroy a sandbox."""
        sandbox_id = await sandbox.create("tenant", "session")
        workdir = sandbox._workdirs[sandbox_id]

        assert workdir.exists()

        await sandbox.destroy(sandbox_id)

        assert sandbox_id not in sandbox._workdirs
        assert not workdir.exists()

    @pytest.mark.asyncio
    async def test_destroy_nonexistent_sandbox(self, sandbox: LocalSandbox) -> None:
        """Destroying non-existent sandbox is a no-op."""
        # Should not raise
        await sandbox.destroy("nonexistent-sandbox")


class TestCloudflareSandbox:
    """Tests for CloudflareSandbox."""

    def test_requires_credentials(self) -> None:
        """Cloudflare sandbox requires account_id and api_token."""
        with pytest.raises(ValueError, match="requires account_id and api_token"):
            CloudflareSandbox()

    def test_init_with_credentials(self) -> None:
        """Initialize with credentials."""
        sandbox = CloudflareSandbox(
            account_id="test-account",
            api_token="test-token",
            limits={"timeout_seconds": 30},
        )

        assert sandbox.account_id == "test-account"
        assert sandbox.api_token == "test-token"

    @pytest.mark.asyncio
    async def test_create_not_implemented(self) -> None:
        """Create raises NotImplementedError."""
        sandbox = CloudflareSandbox(
            account_id="test-account",
            api_token="test-token",
        )

        with pytest.raises(NotImplementedError):
            await sandbox.create("tenant", "session")

    @pytest.mark.asyncio
    async def test_execute_not_implemented(self) -> None:
        """Execute raises NotImplementedError."""
        sandbox = CloudflareSandbox(
            account_id="test-account",
            api_token="test-token",
        )

        with pytest.raises(NotImplementedError):
            await sandbox.execute("sandbox-id", "print('test')")

    @pytest.mark.asyncio
    async def test_destroy_not_implemented(self) -> None:
        """Destroy raises NotImplementedError."""
        sandbox = CloudflareSandbox(
            account_id="test-account",
            api_token="test-token",
        )

        with pytest.raises(NotImplementedError):
            await sandbox.destroy("sandbox-id")
