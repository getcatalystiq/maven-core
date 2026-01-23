"""Local filesystem-based file storage."""

import hashlib
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maven_core.protocols.file_store import FileMetadata


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
        """Get the filesystem path for a key."""
        # Validate key to prevent path traversal
        if ".." in key or key.startswith("/"):
            raise ValueError(f"Invalid key: {key}")
        return self.base_path / key

    def _compute_etag(self, content: bytes) -> str:
        """Compute ETag for content."""
        return hashlib.md5(content).hexdigest()

    def _get_metadata(self, path: Path, key: str) -> FileMetadata:
        """Get metadata for a file."""
        stat = path.stat()
        content = path.read_bytes()
        return FileMetadata(
            key=key,
            size=stat.st_size,
            content_type=None,  # Could detect from extension
            etag=self._compute_etag(content),
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )

    async def put(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> FileMetadata:
        """Store a file."""
        path = self._get_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

        return FileMetadata(
            key=key,
            size=len(content),
            content_type=content_type,
            etag=self._compute_etag(content),
            last_modified=datetime.now(timezone.utc),
        )

    async def get(self, key: str) -> tuple[bytes, FileMetadata] | None:
        """Retrieve a file and its metadata."""
        path = self._get_path(key)
        if not path.exists():
            return None

        content = path.read_bytes()
        metadata = self._get_metadata(path, key)
        return content, metadata

    async def head(self, key: str) -> FileMetadata | None:
        """Get file metadata without content."""
        path = self._get_path(key)
        if not path.exists():
            return None

        return self._get_metadata(path, key)

    async def delete(self, key: str) -> None:
        """Delete a file."""
        path = self._get_path(key)
        if path.exists():
            path.unlink()

    async def list(self, prefix: str) -> AsyncIterator[FileMetadata]:
        """List files matching a prefix."""
        prefix_path = self._get_path(prefix) if prefix else self.base_path
        base = prefix_path if prefix_path.is_dir() else prefix_path.parent

        if not base.exists():
            return

        for path in base.rglob("*"):
            if path.is_file():
                key = str(path.relative_to(self.base_path))
                yield self._get_metadata(path, key)
