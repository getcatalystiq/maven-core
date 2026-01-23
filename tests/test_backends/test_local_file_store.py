"""Tests for local file storage backend."""

import tempfile
from pathlib import Path

import pytest

from maven_core.backends.files.local import LocalFileStore


@pytest.fixture
def file_store():
    """Create a temporary file store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield LocalFileStore(path=tmpdir)


class TestLocalFileStore:
    """Tests for LocalFileStore."""

    @pytest.mark.asyncio
    async def test_put_and_get(self, file_store):
        """Test storing and retrieving a file."""
        content = b"Hello, World!"
        metadata = await file_store.put("test.txt", content)

        assert metadata.key == "test.txt"
        assert metadata.size == len(content)

        result = await file_store.get("test.txt")
        assert result is not None
        retrieved_content, retrieved_metadata = result
        assert retrieved_content == content

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, file_store):
        """Test getting a file that doesn't exist."""
        result = await file_store.get("nonexistent.txt")
        assert result is None

    @pytest.mark.asyncio
    async def test_head(self, file_store):
        """Test getting metadata without content."""
        content = b"Test content"
        await file_store.put("test.txt", content)

        metadata = await file_store.head("test.txt")
        assert metadata is not None
        assert metadata.size == len(content)

    @pytest.mark.asyncio
    async def test_head_nonexistent(self, file_store):
        """Test head for nonexistent file."""
        metadata = await file_store.head("nonexistent.txt")
        assert metadata is None

    @pytest.mark.asyncio
    async def test_delete(self, file_store):
        """Test deleting a file."""
        await file_store.put("test.txt", b"content")
        await file_store.delete("test.txt")

        result = await file_store.get("test.txt")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, file_store):
        """Test deleting a file that doesn't exist (should not raise)."""
        await file_store.delete("nonexistent.txt")  # Should not raise

    @pytest.mark.asyncio
    async def test_list(self, file_store):
        """Test listing files."""
        await file_store.put("dir/file1.txt", b"content1")
        await file_store.put("dir/file2.txt", b"content2")
        await file_store.put("other/file3.txt", b"content3")

        files = []
        async for metadata in file_store.list("dir/"):
            files.append(metadata.key)

        assert len(files) == 2
        assert "dir/file1.txt" in files
        assert "dir/file2.txt" in files

    @pytest.mark.asyncio
    async def test_nested_directory(self, file_store):
        """Test storing files in nested directories."""
        content = b"nested content"
        metadata = await file_store.put("a/b/c/file.txt", content)

        result = await file_store.get("a/b/c/file.txt")
        assert result is not None
        assert result[0] == content

    def test_path_traversal_prevention(self, file_store):
        """Test that path traversal is prevented."""
        with pytest.raises(ValueError):
            file_store._get_path("../../../etc/passwd")

        with pytest.raises(ValueError):
            file_store._get_path("/etc/passwd")
