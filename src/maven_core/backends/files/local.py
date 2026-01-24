"""Local filesystem-based file storage."""

import atexit
import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from maven_core.protocols.file_store import FileMetadata

# Thread pool for async file I/O - configurable via environment
_max_workers = int(os.environ.get("MAVEN_FILE_WORKERS", "16"))
_executor = ThreadPoolExecutor(max_workers=_max_workers)

# Ensure executor is cleaned up on process exit
atexit.register(_executor.shutdown, wait=False)


class LocalFileStore:
    """File storage using the local filesystem.

    Suitable for development and single-server deployments.
    """

    def __init__(self, path: str | None = None, **kwargs: Any) -> None:
        """Initialize local file store.

        Args:
            path: Base directory for file storage. Defaults to ./data/files
            **kwargs: Ignored (for compatibility with other backends)
        """
        self.base_path = Path(path) if path else Path("./data/files")
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        """Get the filesystem path for a key.

        Validates the key to prevent path traversal attacks,
        including URL-encoded sequences.
        """
        # Decode URL-encoded characters first to catch encoded traversal attempts
        decoded_key = unquote(key)

        # Validate key to prevent path traversal
        if ".." in decoded_key or decoded_key.startswith("/"):
            raise ValueError(f"Invalid key: {key}")

        # Check for null bytes and other dangerous characters
        if "\x00" in decoded_key or "\\" in decoded_key:
            raise ValueError(f"Invalid key: {key}")

        target_path = (self.base_path / decoded_key).resolve()

        # Verify the resolved path is within base_path (defense in depth)
        try:
            target_path.relative_to(self.base_path.resolve())
        except ValueError:
            raise ValueError(f"Invalid key: path traversal detected")

        return target_path

    def _compute_etag(self, content: bytes) -> str:
        """Compute ETag for content."""
        return hashlib.md5(content).hexdigest()

    def _get_metadata(self, path: Path, key: str) -> FileMetadata:
        """Get metadata for a file.

        Uses stat-based ETag (inode, size, mtime) to avoid reading file content.
        """
        stat = path.stat()
        # Use stat-based ETag: inode-size-mtime (avoids full file read)
        etag = f"{stat.st_ino}-{stat.st_size}-{int(stat.st_mtime * 1000)}"
        return FileMetadata(
            key=key,
            size=stat.st_size,
            content_type=None,  # Could detect from extension
            etag=hashlib.md5(etag.encode()).hexdigest(),
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )

    async def put(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> FileMetadata:
        """Store a file asynchronously."""
        path = self._get_path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        # Run blocking I/O in thread pool
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_executor, _write)

        return FileMetadata(
            key=key,
            size=len(content),
            content_type=content_type,
            etag=self._compute_etag(content),
            last_modified=datetime.now(timezone.utc),
        )

    async def get(self, key: str) -> tuple[bytes, FileMetadata] | None:
        """Retrieve a file and its metadata asynchronously."""
        path = self._get_path(key)

        def _read() -> tuple[bytes, FileMetadata] | None:
            if not path.exists():
                return None
            content = path.read_bytes()
            metadata = self._get_metadata(path, key)
            return content, metadata

        # Run blocking I/O in thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, _read)

    async def head(self, key: str) -> FileMetadata | None:
        """Get file metadata without content asynchronously."""
        path = self._get_path(key)

        def _head() -> FileMetadata | None:
            if not path.exists():
                return None
            return self._get_metadata(path, key)

        # Run blocking I/O in thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, _head)

    async def delete(self, key: str) -> None:
        """Delete a file asynchronously."""
        path = self._get_path(key)

        def _delete() -> None:
            if path.exists():
                path.unlink()

        # Run blocking I/O in thread pool
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(_executor, _delete)

    async def list(self, prefix: str) -> AsyncIterator[FileMetadata]:
        """List files matching a prefix."""
        prefix_path = self._get_path(prefix) if prefix else self.base_path
        base = prefix_path if prefix_path.is_dir() else prefix_path.parent

        if not base.exists():
            return

        def _list_files() -> list[tuple[Path, str]]:
            """List files in thread pool to avoid blocking."""
            results = []
            # Resolve base_path to handle symlinks consistently (e.g., /var -> /private/var on macOS)
            resolved_base = self.base_path.resolve()
            for path in base.rglob("*"):
                if path.is_file():
                    # Use resolved paths to handle symlinks consistently
                    key = str(path.resolve().relative_to(resolved_base))
                    results.append((path, key))
            return results

        # Run blocking I/O in thread pool
        loop = asyncio.get_running_loop()
        files = await loop.run_in_executor(_executor, _list_files)

        for path, key in files:
            yield self._get_metadata(path, key)
