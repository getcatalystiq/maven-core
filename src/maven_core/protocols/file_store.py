"""FileStore protocol for file storage backends."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class FileMetadata:
    """Metadata returned from file operations."""

    key: str
    size: int
    content_type: str | None
    etag: str
    last_modified: datetime


class FileStore(Protocol):
    """Protocol for file storage backends (R2, S3, filesystem)."""

    async def put(
        self,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> FileMetadata:
        """Store a file and return its metadata."""
        ...

    async def get(self, key: str) -> tuple[bytes, FileMetadata] | None:
        """Retrieve a file and its metadata. Returns None if not found."""
        ...

    async def head(self, key: str) -> FileMetadata | None:
        """Get file metadata without downloading content. Returns None if not found."""
        ...

    async def delete(self, key: str) -> None:
        """Delete a file. No-op if file doesn't exist."""
        ...

    async def list(self, prefix: str) -> AsyncIterator[FileMetadata]:
        """List files matching a prefix."""
        ...
